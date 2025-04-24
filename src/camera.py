from livekit import rtc
import logging
from time import sleep
from picamera2 import Picamera2


class Camera:
    def __init__(self):
        self.recording = False
        self.pi_camerra = False
        self.cam = Picamera2()        

    def video_loop(self, source: rtc.VideoSource, WIDTH=640, HEIGHT=480):
        self.cam.configure(self.cam.create_video_configuration(main={"format": 'XBGR8888', "size": (WIDTH, HEIGHT)}))
        self.cam.start()
        self.recording = True
            
            # Create an array to store the frame
        while self.recording:
            frame = self.cam.capture_array()

            source.capture_frame(
                rtc.VideoFrame(WIDTH, HEIGHT, rtc.VideoBufferType.RGBA, frame))
            # sleep(0.1)
        logging.info("Video stream closed")


camera = Camera()
