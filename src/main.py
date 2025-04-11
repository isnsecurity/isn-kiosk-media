import asyncio
import threading
from time import sleep, time
import sys
import logging
import os
import numpy as np
import yaml


from livekit import api, rtc
import cv2
import pyaudio
import firebase_admin
from firebase_admin import credentials, firestore
from tools.request.client import RestClient
from speaker import speaker


WIDTH, HEIGHT = 1024, 576
MIC_RATE = 48000
RATE = 48000
MIC_CHUNK = 1024
SPEAKER_CHUNK = 1024
CHUNK = 4096
NUM_CHANNELS = 1

# p = pyaudio.PyAudio()


async def play_audio(audio_stream: rtc.AudioStream):
    # p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16,
                    channels=1,
                    rate=RATE,
                    output=True)
    await asyncio.sleep(1)
    async for frame in audio_stream:
        if not speaker.running:
            break
        try:
            data = frame.frame.data.tobytes()
            # print(len(data))
            stream.write(data, exception_on_underflow=False)
        except IOError as e:
            print(f"Audio playback error: {e}")
            break
        # await asyncio.sleep(0.001)
    # asyncio.run(write_audio(audio_stream))
    # stream.stop_stream()
    # stream.close()
    logging.info("Audio stream closed")


async def main(room: rtc.Room):
    CREDENTIALS = "secrets/isncustomers-prod.json"
    cred = credentials.Certificate(CREDENTIALS)
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    device_id = yaml.safe_load(open("settings.yaml"))['devide_id']
    kiosks = db.collection('kiosks')
    device = kiosks.document(device_id).get()
    calls = db.collection('kiosk-calls')

    phone = ""
    if len(sys.argv) > 1:
        phone = sys.argv[1]
    else:
        raise Exception("No phone entered")
    # f"Kiosk Call to {phone} at {time()}"
    room_name = f"Kiosk Call to {phone}"

    @room.on("participant_connected")
    def on_participant_connected(participant: rtc.RemoteParticipant) -> None:
        logging.info(
            "participant connected: %s %s", participant.sid, participant.identity
        )

    @room.on("participant_disconnected")
    def on_participant_disconnected(participant: rtc.RemoteParticipant) -> None:
        logging.info(
            "participant disconnected: %s %s", participant.sid, participant.identity
        )

    @room.on("active_speakers_changed")
    def on_active_speakers_changed(speakers: list[rtc.RemoteParticipant]) -> None:
        # logging.info(
        #     "active speakers changed: %s",
        #     [f"{s.identity}, {s.track_publications}" for s in speakers]
        # )
        pass

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
            logging.info(
                "Subscribed to an Audio Track %s", track.sid)
            # speaker.stop()
            speaker.running = False
            audio_stream = rtc.AudioStream(track)
            # speaker.play(audio_stream)
            # speaker.play_in_loop(audio_stream)

            def play_audio_wrapper(audio_stream: rtc.AudioStream):
                asyncio.run(play_audio(audio_stream))

            remote_audio_thread = threading.Thread(
                name="remote_audio_thread",
                target=play_audio_wrapper,
                args=(audio_stream,),
                daemon=False
            )
            speaker.running = True
            remote_audio_thread.start()
            # asyncio.ensure_future(play_audio(audio_stream))

    @room.on("track_unsubscribed")
    def on_track_unsubscribed(track: rtc.Track) -> None:
        if isinstance(track, rtc.AudioTrack):
            logging.info("Unsubscribed from Audio Track %s", track.sid)
            speaker.running = False

    token = device.to_dict().get('token', None)
    if not token:
        token = (
            api.AccessToken()
            .with_identity("guest-kiosk")
            .with_name("Guest")
            .with_grants(
                api.VideoGrants(
                    room_join=True,
                    room=room_name,
                )
            )
            .to_jwt()
        )
        kiosks.document(device_id).set({
            'token': token,
        })

    client_document = calls.document(phone).get()
    client_token = client_document.to_dict().get('token', None)
    if not client_token:
        client_token = (
            api.AccessToken()
            .with_identity("jose-mobile")
            .with_name("Jose")
            .with_grants(
                api.VideoGrants(
                    room_join=True,
                    room=room_name,
                )
            )
            .to_jwt()
        )
        calls.document(phone).set({
            'status': 'pending',
            'token': client_token,
            'room': room_name,
            'timestamp': time(),
        })
    else:
        calls.document(phone).update({
            'status': 'pending',
            'room': room_name,
            'timestamp': time(),
        })

    request = RestClient(os.getenv("PUSH_NOTIFICATION_URL"))
    data = {
        "data": {
            "phones": [phone],  # "7867262434"
            "priority": "high",
            "variables": {
                "callToken": client_token,
                "title": "Community Gate Call",
                "message": "You have a call from back gate. Please click to answer."
            }
        }
    }

    # wss://isn-media-xunj78xl.livekit.cloud
    # API6rvatVYtTGCf
    # bskUSEzA8BGNehB2YgGu1jDH06f8ReAH332RCeIaX77B

    url = os.getenv("LIVEKIT_URL")
    lkapi = api.LiveKitAPI(url)
    # logging.info("Creating room")
    # await lkapi.room.create_room(
    #     api.CreateRoomRequest(name=room_name),
    # )
    # logging.info("Room created")

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
    local_video_thread.start()
    asyncio.ensure_future(audio_loop(audio_source))
    # local_audio_thread.start()

    # await asyncio.gather(audio_loop(audio_source), video_loop(source))
    # response = json.loads(request.send(data))
    # if response.get("status") == "success":
    #     logging.info("Push notification sent")
    logging.info("Call Connected")


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
    pe = pyaudio.PyAudio()
    stream = pe.open(format=pyaudio.paInt16,
                     channels=1,
                     rate=RATE,
                     input=True,
                     frames_per_buffer=MIC_CHUNK)
    try:
        while True:
            start = time()
            data = stream.read(MIC_CHUNK)
            elapsed_ms = (time() - start) * 1000
            audio_array = np.frombuffer(data, dtype=np.int16)
            amplitude = np.abs(audio_array).mean()
            # logging.info(
            #     f"Audio capture took: {elapsed_ms:.2f}ms, Amplitude: {amplitude:.2f}")
            frame = rtc.AudioFrame(data, RATE, NUM_CHANNELS, MIC_CHUNK)
            await audio_source.capture_frame(frame)
            # await asyncio.sleep(0.01)
    finally:
        stream.stop_stream()
        stream.close()
        pe.terminate()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        handlers=[logging.FileHandler(
            "isn-kiosk-media.log"), logging.StreamHandler()],
    )
    p = speaker.p  # pyaudio.PyAudio()
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
