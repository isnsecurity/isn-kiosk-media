
import threading
import asyncio
import logging
import pyaudio
from livekit import rtc


class Speaker:

    def __init__(self, rate=48000):
        super().__init__()
        self.p = pyaudio.PyAudio()
        # logging.info("using: %s", self.p.get_default_output_device_info())
        self.stream = self.p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=rate,
            output=True
        )
        self.running = False
        # self.speaker_loop = asyncio.new_event_loop()
        # thread = threading.Thread(
        #     name="speaker_loop",
        #     daemon=False,
        #     target=self.run_speaker_loop
        # )
        # thread.start()

    def run_speaker_loop(self):
        """
        Run the speaker loop.
        """
        asyncio.set_event_loop(self.speaker_loop)
        self.speaker_loop.run_forever()

    def play(self, audio_stream: rtc.AudioStream):
        """
        Play the audio stream.
        :param audio_stream: AudioStream object from livekit
        """
        self.running = True
        # Read the audio stream and play it

        async def play_audio(audio_stream: rtc.AudioStream):
            async for frame in audio_stream:
                try:
                    data = frame.frame.data.tobytes()
                    print(len(data))
                    self.stream.write(data,
                                      exception_on_underflow=False)
                except IOError as e:
                    print(f"Audio playback error: {e}")
                if not self.running:
                    break

        def play_audio_wrapper(audio_stream: rtc.AudioStream):
            asyncio.run(play_audio(audio_stream))
        # Start the audio stream
        audio_thread = threading.Thread(
            name="play_remote_audio",
            target=play_audio_wrapper,
            args=(audio_stream,)
        )
        audio_thread.start()

    async def play_audio(self, audio_stream: rtc.AudioStream):
        """
        Play the audio stream.
        :param audio_stream: AudioStream object from livekit
        """
        async for frame in audio_stream:
            try:
                data = frame.frame.data.tobytes()
                print(len(data))
                self.stream.write(data, exception_on_underflow=False)
            except IOError as e:
                print(f"Audio playback error: {e}")
                self.stream.stop_stream()
            except OSError as e:
                print(f"Audio playback error: {e}")
                self.stream.stop_stream()

    def play_in_loop(self, audio_stream: rtc.AudioStream):
        asyncio.run_coroutine_threadsafe(
            self.play_audio(audio_stream), self.speaker_loop)

    def stop(self):
        """
        Stop the audio stream.
        """
        self.running = False
        self.stream.stop_stream()
        self.stream.close()
        self.p.terminate()


speaker = Speaker(rate=48000)
