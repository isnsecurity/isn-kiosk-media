import asyncio
import threading
from time import sleep, time
import numpy as np
import logging
import os
from typing import Union
import json

from livekit import api, rtc
import cv2
import pyaudio
from tools.request.client import RestClient


WIDTH, HEIGHT = 1024, 576
RATE = 48000
CHUNK = 2048
NUM_CHANNELS = 1


async def play_audio(audio_stream: rtc.AudioStream):
    p = pyaudio.PyAudio()
    output_stream = p.open(format=pyaudio.paInt16,
                           channels=1,
                           rate=RATE,
                           output=True)
    async for frame in audio_stream:
        output_stream.write(frame.frame.data.tobytes())


def remote_audio_processing(audio_stream: rtc.AudioStream):
    try:
        asyncio.run(play_audio(audio_stream))
    except Exception as e:
        logging.error("Error processing remote audio: %s", e)


async def main(room: rtc.Room):
    @room.on("participant_connected")
    def on_participant_connected(participant: rtc.RemoteParticipant) -> None:
        logging.info(
            "participant connected: %s %s", participant.sid, participant.identity
        )

    @room.on("local_track_published")
    def on_local_track_published(
        publication: rtc.LocalTrackPublication,
        track: Union[rtc.LocalAudioTrack, rtc.LocalVideoTrack],
    ):
        logging.info("local track published: %s", publication.sid)

    @room.on("data_received")
    def on_data_received(data: rtc.DataPacket):
        logging.info("received data from %s: %s",
                     data.participant.identity, data.data)

    @room.on("track_subscribed")
    def on_track_subscribed(
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ):
        logging.info("track subscribed: %s", publication.sid)
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            print("Subscribed to an Audio Track")
            audio_stream = rtc.AudioStream(track)
            remote_audio_thread = threading.Thread(
                name="remote_audio_thread",
                target=remote_audio_processing,
                args=(audio_stream,),
                daemon=True
            )
            remote_audio_thread.start()

    token = (
        api.AccessToken()
        .with_identity("guest-kiosk")
        .with_name("Guest")
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room="Kiosk Call",
            )
        )
        .to_jwt()
    )

    client_token = (
        api.AccessToken()
        .with_identity("jose-mobile")
        .with_name("Jose")
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room="Kiosk Call",
            )
        )
        .to_jwt()
    )
    logging.info(client_token)
    request = RestClient(os.getenv("PUSH_NOTIFICATION_URL"))
    data = {
        "data": {
            "phones": ["7867262434"],
            "priority": "high",
            "variables": {
                "callToken": client_token,
                "title": "Community Gate Call",
                "message": "You have a call from back gate. Please click to answer."
            }
        }
    }

    logging.info("Push notification sent")

    # wss://isn-media-xunj78xl.livekit.cloud
    # API6rvatVYtTGCf
    # bskUSEzA8BGNehB2YgGu1jDH06f8ReAH332RCeIaX77B

    url = os.getenv("LIVEKIT_URL")
    lkapi = api.LiveKitAPI(url)
    logging.info("Creating room")
    room_info = await lkapi.room.create_room(
        api.CreateRoomRequest(name="Kiosk Call"),
    )
    logging.info("Room created")

    await lkapi.aclose()

    logging.info("connecting to %s", url)
    try:
        await room.connect(url, token)
        logging.info("connected to room %s", room.name)
    except rtc.ConnectError as e:
        logging.error("failed to connect to the room: %s", e.message)
        return

    # publish a video track
    source = rtc.VideoSource(WIDTH, HEIGHT)
    track = rtc.LocalVideoTrack.create_video_track("hue", source)
    options = rtc.TrackPublishOptions()
    options.source = rtc.TrackSource.SOURCE_CAMERA
    publication = await room.local_participant.publish_track(track, options)
    logging.info("published video track %s", publication.sid)

    # publich a audio track
    audio_source = rtc.AudioSource(RATE, NUM_CHANNELS)
    audio_track = rtc.LocalAudioTrack.create_audio_track(
        "mic", audio_source)
    audio_options = rtc.TrackPublishOptions()
    audio_options.source = rtc.TrackSource.SOURCE_MICROPHONE
    audio_publication = await room.local_participant.publish_track(
        audio_track, audio_options)
    logging.info("published audio track %s", audio_publication.sid)
    threads = [x.name for x in threading.enumerate()
               if "pydevd" not in x.name]
    logging.info('Threads %s: %s', len(threads), threads)
    # asyncio.ensure_future(video_loop(source, audio_source))
    local_audio_thread = threading.Thread(
        name="local_audio_thread",
        target=audio_loop,
        args=(audio_source,),
        daemon=True
    )
    local_video_thread = threading.Thread(
        name="local_video_thread",
        target=video_loop,
        args=(source,),
        daemon=True
    )
    local_audio_thread.start()
    local_video_thread.start()
    # await asyncio.gather(audio_loop(audio_source), video_loop(source))
    response = json.loads(request.send(data))
    if response.get("status") == "success":
        logging.info("Push notification sent")


def video_loop(source: rtc.VideoSource):
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
    while True:
        _, frame = cap.read()
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGBA)
        # rezise image to portrait
        # new_width = 300
        # new_height = 576
        # frame = cv2.resize(frame, (new_width, new_height))

        source.capture_frame(
            rtc.VideoFrame(WIDTH, HEIGHT, rtc.VideoBufferType.RGBA, frame))
        sleep(0.1)

        # cv2.imshow("frame", frame)
        # if cv2.waitKey(1) & 0xFF == ord('q'):
        #     break
    cap.release()
    # Destroy all the windows
    cv2.destroyAllWindows()


def audio_loop(audio_source: rtc.AudioSource):
    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16,
                    channels=1,
                    rate=RATE,
                    input=True,
                    frames_per_buffer=CHUNK)
    try:
        while True:
            start = time()
            data = stream.read(CHUNK)
            elapsed_ms = (time() - start) * 1000
            audio_array = np.frombuffer(data, dtype=np.int16)
            amplitude = np.abs(audio_array).mean()
            logging.info(
                f"Audio capture took: {elapsed_ms:.2f}ms, Amplitude: {amplitude:.2f}")
            frame = rtc.AudioFrame(data, RATE, NUM_CHANNELS, CHUNK)
            asyncio.run(audio_source.capture_frame(frame))
            asyncio.run(asyncio.sleep(0.01))
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        handlers=[logging.FileHandler(
            "isn-kiosk-media.log"), logging.StreamHandler()],
    )
    # p = pyaudio.PyAudio()
    # for i in range(p.get_device_count()):
    #     logging.info(p.get_device_info_by_index(i))
    # logging.info(p.get_default_input_device_info())
    # logging.info(p.get_default_output_device_info())

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    room = rtc.Room(loop=loop)

    async def cleanup():
        await room.disconnect()
        loop.stop()

    asyncio.ensure_future(main(room))

    try:
        loop.run_forever()
    except Exception as e:
        logging.error("Error occurred: %s", e)
    finally:
        loop.close()

    cleanup()
