import asyncio
import colorsys
import logging
import os

import numpy as np
from livekit import api, rtc
import cv2
import pyaudio
from pvrecorder import PvRecorder


WIDTH, HEIGHT = 1024, 576
RATE = 44100
NUM_CHANNELS = 1


async def main(room: rtc.Room):
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
    audio_track = rtc.LocalAudioTrack.create_audio_track("mic", audio_source)
    audio_options = rtc.TrackPublishOptions()
    audio_options.source = rtc.TrackSource.SOURCE_MICROPHONE
    audio_publication = await room.local_participant.publish_track(
        audio_track, audio_options)
    logging.info("published audio track %s", audio_publication.sid)

    # asyncio.ensure_future(draw_color_cycle(source))
    # asyncio.ensure_future(video_loop(source, audio_source))
    await asyncio.gather(audio_loop(audio_source), video_loop(source))


async def draw_color_cycle(source: rtc.VideoSource):
    argb_frame = bytearray(WIDTH * HEIGHT * 4)
    arr = np.frombuffer(argb_frame, dtype=np.uint8)

    framerate = 1 / 30
    hue = 0.0

    while True:
        start_time = asyncio.get_event_loop().time()

        rgb = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
        rgb = [(x * 255) for x in rgb]  # type: ignore

        argb_color = np.array(rgb + [255], dtype=np.uint8)
        arr.flat[::4] = argb_color[0]
        arr.flat[1::4] = argb_color[1]
        arr.flat[2::4] = argb_color[2]
        arr.flat[3::4] = argb_color[3]

        frame = rtc.VideoFrame(
            WIDTH, HEIGHT, rtc.VideoBufferType.RGBA, argb_frame)
        source.capture_frame(frame)
        hue = (hue + framerate / 3) % 1.0

        code_duration = asyncio.get_event_loop().time() - start_time
        await asyncio.sleep(1 / 30 - code_duration)


async def video_loop(source: rtc.VideoSource):
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
    while True:
        _, frame = cap.read()
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGBA)
        source.capture_frame(
            rtc.VideoFrame(WIDTH, HEIGHT, rtc.VideoBufferType.RGBA, frame))
        await asyncio.sleep(0.06)

        # cv2.imshow("frame", frame)
        # if cv2.waitKey(1) & 0xFF == ord('q'):
        #     break
    cap.release()
    # Destroy all the windows
    cv2.destroyAllWindows()


async def audio_loop(audio_source: rtc.AudioSource):
    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16,
                    channels=1,
                    rate=44100,
                    input=True,
                    frames_per_buffer=1024)

    while True:
        data = stream.read(1024)
        frame = rtc.AudioFrame(data, RATE, NUM_CHANNELS, 1024)
        await audio_source.capture_frame(frame)

    stream.stop_stream()
    stream.close()
    p.terminate()


async def audio_loop2(audio_source: rtc.AudioSource):
    for index, device in enumerate(PvRecorder.get_available_devices()):
        print(f"[{index}] {device}")
    recorder = PvRecorder(device_index=1, frame_length=512,
                          buffered_frames_count=50)

    try:
        recorder.start()

        while True:
            data = recorder.read()
            frame = rtc.AudioFrame(data, 48000, 1, 480)
            await audio_source.capture_frame(frame)
            # Do something ...
    except KeyboardInterrupt:
        recorder.stop()
    finally:
        recorder.delete()

    stream.stop_stream()
    stream.close()
    p.terminate()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        handlers=[logging.FileHandler(
            "publish_hue.log"), logging.StreamHandler()],
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    room = rtc.Room(loop=loop)

    async def cleanup():
        await room.disconnect()
        loop.stop()

    asyncio.ensure_future(main(room))

    try:
        loop.run_forever()
    finally:
        loop.close()

    cleanup()
