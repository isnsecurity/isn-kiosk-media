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
import firebase_admin
from firebase_admin import credentials, firestore
from tools.request.client import RestClient


WIDTH, HEIGHT = 1024, 576
MIC_RATE = 48000
RATE = 48000
CHUNK = 4096
NUM_CHANNELS = 1

async def play_audio(audio_stream: rtc.AudioStream):
    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16,
                           channels=1,
                           rate=RATE,
                           output=True)    
    async for frame in audio_stream:
        stream.write(frame.frame.data.tobytes())
        # await asyncio.sleep(0.01)
    asyncio.run(write_audio(audio_stream))
    stream.stop_stream()
    stream.close()
    p.terminate()


async def main(room: rtc.Room):
    CREDENTIALS = "secrets/dev/isn-suite-dev-370915-firebase-adminsdk-sn531-7e70dbe832.json"
    cred = credentials.Certificate(CREDENTIALS)
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    calls = db.collection('kiosk-calls')

    @room.on("participant_connected")
    def on_participant_connected(participant: rtc.RemoteParticipant) -> None:
        logging.info(
            "participant connected: %s %s", participant.sid, participant.identity
        )

    # @room.on("local_track_published")
    # def on_local_track_published(
    #     publication: rtc.LocalTrackPublication,
    #     track: Union[rtc.LocalAudioTrack, rtc.LocalVideoTrack],
    # ):
    #     logging.info("local track published: %s", publication.sid)

    @room.on("data_received")
    def on_data_received(data: rtc.DataPacket):
        logging.info("received data from %s: %s",
                     data.participant.identity, data.data)

    @room.on("track_subscribed")
    def on_track_subscribed(
        track: rtc.Track
    ):
        if isinstance(track, rtc.AudioTrack):
            logging.info("Subscribed to an Audio Track")
            audio_stream = rtc.AudioStream(track)
            # remote_audio_thread = threading.Thread(
            #     name="remote_audio_thread",
            #     target=play_audio,
            #     args=(audio_stream,),
            #     daemon=True
            # )
            # remote_audio_thread.start()
            asyncio.ensure_future(play_audio(audio_stream))


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
    calls.document("7866563928").set({
        'status': 'pending',
        'token': client_token,
        'room': "Kiosk Call",
        'timestamp': time(),
    })

    # request = RestClient(os.getenv("PUSH_NOTIFICATION_URL"))
    # data = {
    #     "data": {
    #         "phones": ["7867262434"],
    #         "priority": "high",
    #         "variables": {
    #             "callToken": client_token,
    #             "title": "Community Gate Call",
    #             "message": "You have a call from back gate. Please click to answer."
    #         }
    #     }
    # }

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
    audio_source = rtc.AudioSource(MIC_RATE, NUM_CHANNELS)
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
    def audio_loop_wrapper(audio_source: rtc.AudioSource):
        asyncio.run(audio_loop(audio_source))
    
    local_audio_thread = threading.Thread(
        name="local_audio_thread",
        target=audio_loop_wrapper,
        args=(audio_source,),
        daemon=True
    )
    local_video_thread = threading.Thread(
        name="local_video_thread",
        target=video_loop,
        args=(source,),
        daemon=True
    )
    asyncio.ensure_future(audio_loop(audio_source))
    # local_audio_thread.start()
    local_video_thread.start()
    # await asyncio.gather(audio_loop(audio_source), video_loop(source))
    # response = json.loads(request.send(data))
    # if response.get("status") == "success":
    #     logging.info("Push notification sent")


def video_loop(source: rtc.VideoSource):
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
    try:
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
    finally:
        cap.release()
        # Destroy all the windows
        cv2.destroyAllWindows()


async def audio_loop(audio_source: rtc.AudioSource):
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
            await audio_source.capture_frame(frame)
            # await asyncio.sleep(0.01)
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
    local_room = rtc.Room(loop=loop)

    async def cleanup():
        await local_room.disconnect()
        loop.stop()

    asyncio.ensure_future(main(local_room))

    try:
        loop.run_forever()
    except Exception as e:
        logging.error("Error occurred: %s", e)
    finally:
        loop.close()

    cleanup()
