import asyncio
from livekit import rtc, api
from picamera2 import Picamera2
import pyaudio
import numpy as np

# LiveKit Cloud configuration
LIVEKIT_URL = "https://isn-media-273rhf15.livekit.cloud"  # Replace with your LiveKit Cloud URL
API_KEY = "APInEzbJNoMNLxf"                         # From LiveKit Cloud dashboard
API_SECRET = "e9gy6um4AoHzAjCXPLUiSUe2NYdvj3b23zJnxKHUOy9"                   # From LiveKit Cloud dashboard
ROOM_NAME = "Kiosk Call"
USER_IDENTITY = "kiosk-pi"

# Audio configuration
CHUNK_SIZE = 1024
SAMPLE_RATE = 48000  # LiveKit expects 48kHz
CHANNELS = 1

async def main():
    # Generate access token
    token = api.AccessToken(API_KEY, API_SECRET) \
        .with_identity(USER_IDENTITY) \
        .with_name("Kiosk Pi") \
        .with_grants(api.VideoGrants(
            room_join=True,
            room=ROOM_NAME,
        )).to_jwt()

    # Initialize room
    room = rtc.Room()

    # Connect to LiveKit Cloud
    await room.connect(LIVEKIT_URL, token)
    print(f"Connected to room: {ROOM_NAME}")

    # Set up camera with picamera2
    picam = Picamera2()
    config = picam.create_video_configuration(main={"size": (640, 480), "format": "YUV420"})
    picam.configure(config)
    picam.start()

    # Custom VideoSource for Pi Camera
    class PiVideoSource(rtc.VideoSource):
        def __init__(self):
            super().__init__(width=640, height=480, frame_rate=30)

        async def capture_frame(self):
            frame = picam.capture_array()
            # Convert YUV420 to a format LiveKit can use (e.g., NV12 or RGB)
            # For simplicity, we'll assume RGB conversion here (less efficient)
            rgb_frame = picam.helpers.make_rgb(frame)
            return rtc.VideoFrame(width=640, height=480, data=rgb_frame.tobytes())

    # Set up audio with pyaudio
    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16,
                    channels=CHANNELS,
                    rate=SAMPLE_RATE,
                    input=True,
                    frames_per_buffer=CHUNK_SIZE)

    # Custom AudioSource for microphone
    class PiAudioSource(rtc.AudioSource):
        def __init__(self):
            super().__init__(sample_rate=SAMPLE_RATE, channels=CHANNELS)

        async def capture_frame(self):
            audio_data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
            return rtc.AudioFrame(data=audio_data, sample_rate=SAMPLE_RATE, channels=CHANNELS)

    # Publish video and audio tracks
    video_source = PiVideoSource()
    audio_source = PiAudioSource()
    video_track = rtc.LocalVideoTrack.create_video_track("kiosk-video", video_source)
    audio_track = rtc.LocalAudioTrack.create_audio_track("kiosk-audio", audio_source)

    await room.local_participant.publish_track(video_track)
    await room.local_participant.publish_track(audio_track)
    print("Published video and audio tracks")

    # Event handlers
    @room.on("participant_connected")
    def on_participant_connected(participant: rtc.RemoteParticipant):
        print(f"Mobile user connected: {participant.identity}")

    @room.on("track_subscribed")
    def on_track_subscribed(track: rtc.Track, publication: rtc.RemoteTrackPublication, participant: rtc.RemoteParticipant):
        print(f"Subscribed to {track.kind} track from {participant.identity}")
        # TODO: Add logic to display video (e.g., with a UI framework)

    # Keep the connection alive
    try:
        await asyncio.Future()  # Run indefinitely
    except asyncio.CancelledError:
        await room.disconnect()
        stream.stop_stream()
        stream.close()
        p.terminate()
        picam.stop()
        print("Disconnected and cleaned up")

if __name__ == "__main__":
    asyncio.run(main())