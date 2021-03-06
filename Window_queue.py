import hamamatsu_camera as cam
import tifffile as tiff
import numpy as np
import c_image_manipulation_c as c_image
import time
import threading
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtWidgets import *
import PyDAQmx
import ctypes
import sys
import os
import windowUI as ui
from multiprocessing import Queue

import aotf as aotfui
import stage as Stage
import message
import shutter as shutter
import galvo as Galvo
import synchronization as syn
import tinytiffwriter
import tifffile
import libtiff


class MainWindow:
    def __init__(self):
        super().__init__()
        self.ui=ui.MainWindow()
        self.ui.setupMainWindow()
        self.ui.show()

        self.message=message.Message()
        self.queue=Queue()
        self.frames = []
        self.readout_time=None
        self.lines = None
        self.live_thread_flag = None
        self.record_thread_flag = None
        self.filename = None
        self.rescale_min = 0
        self.rescale_max = 65535
        self.file=None
        self.lock = threading.Lock()
        self.hcam = cam.HamamatsuCameraMR(camera_id=0)

        #self.camera()

        self.ui.shutterButton.clicked.connect(lambda: self.shutterUi())
        self.ui.AOTFButton.clicked.connect(lambda: self.aotfUi())
        self.ui.GalvoButton.clicked.connect(lambda: self.galvoUi())
        self.ui.StageButton.clicked.connect(lambda: self.stageUi())
        self.ui.liveButton.clicked.connect(lambda: self.live_state_change())
        self.ui.recordButton.clicked.connect(lambda: self.record_state_change())
        self.ui.autoscalebutton.clicked.connect(lambda: self.autoscale())
        #self.ui.set_button.clicked.connect(lambda: self.camera())
        self.ui.connectButton.clicked.connect(lambda: self.connect())

        self.live_thread = threading.Thread(target=self.display, name='liveThread')
        self.record_thread = threading.Thread(target=self.recording, name="recordThread")

    def connect(self):
        self.hcam.stopAcquisition()
        self.hcam.setPropertyValue("trigger_polarity", 2)
        self.hcam.setPropertyValue("trigger_active", 1)
        self.aotf.ui.button_analog.setChecked(True)
        self.aotf.analog()
        self.lines=syn.Lines(time_405=float(self.ui.r_405_expo.text()),time_647=float(self.ui.r_647_expo.text()),
                                   frames=float(self.ui.rframes.text()),
                             cycles=float(self.ui.rcycles.text()),exposure=float(self.ui.rcam_expo.text()),
                             stage_range=float(self.ui.range.text()),stage_step=float(self.ui.step.text()))
        self.stage.signal.connect(self.lines.start)
        self.lines.signal.connect(self.stage.move)

    '''def camera(self):
        if self.ui.source.currentText()=='internal':
            self.hcam.setPropertyValue("trigger_source", 1)
            self.message.send_message('trigger source','internal')
            self.readout_time=0
        else:
            self.hcam.setPropertyValue("trigger_source", 2)
            self.message.send_message('trigger source','external')
            if self.ui.active.currentText() == 'edge':
                self.hcam.setPropertyValue("trigger_active", 1)
                self.message.send_message('trigger active','edge')
                self.readout_time = 11
            else:
                self.hcam.setPropertyValue("trigger_active", 3)
                self.message.send_message('trigger active','synchronous')
                self.readout_time = 0'''





    def autoscale(self):
        try:
            self.rescale_min = self.image_min
            self.rescale_max = self.image_max
        except:
            print("not start display yet")

    def get_buffer(self):
            [self.frames, dims] = self.hcam.getFrames()
            print(str(len(self.frames)) + "  frames get")
            if len(self.frames) == 0:
                self.hcam.stopAcquisition()
                self.get_buffer_timer.stop()
                if self.ui.recordButton.isChecked():
                    self.ui.recordButton.setChecked(False)
                    self.ui.recordButton.setText("record")
                    self.record_thread_flag = False
                self.ui.liveButton.setText("live")
                self.ui.liveButton.setChecked(False)
                return (0)

            # pid = os.getpid()
            # print("main PID: " + str(pid))
            print("buffer thread id: " + str(threading.current_thread().name))
            if self.live_thread_flag == True:
                if self.live_thread.is_alive():
                    # print("shutting down living thread")
                    self.live_thread_flag = False
                    time.sleep(0.13)
                    self.live_thread_flag = True
                self.live_thread = threading.Thread(target=self.display, name='liveThread')
                self.live_thread.start()

            if self.record_thread_flag == True:
                if self.record_thread.is_alive():
                    print("recording not finished,data losed")
                else:
                    self.record_thread = threading.Thread(target=self.recording, name="recordThread")
                    self.record_thread.start()

    def live_state_change(self):
            if self.ui.liveButton.isChecked():
                    self.ui.liveButton.setText('stop live')
                    self.live_thread_flag = True
                    self.hcam.startAcquisition()
                    self.hcam.setPropertyValue('exposure_time', float(self.ui.cam_expo.text())/1000.0)
                    self.get_buffer_timer = QtCore.QTimer()
                    self.get_buffer_timer.timeout.connect(lambda: self.get_buffer())
                    self.get_buffer_timer.start(1000)
            else:
                self.live_thread_flag = False
                self.get_buffer_timer.stop()
                self.hcam.stopAcquisition()
                self.ui.liveButton.setText('Live')

    def display(self):
            '''live child thread
            display images when one cycle ends'''
            # pid = os.getpid()
            #print("living PID: " + str(pid))
            print("living thread id: "+str(threading.current_thread().name))
            step = 2
            sleep_time = 100

            for i in range(0, len(self.frames), step):
                # start = time.clock()
                if self.live_thread_flag == True:
                    try:
                        image = self.frames[i].np_array.reshape((2048, 2048))
                    except:
                        break

                    self.lock.acquire()
                    rescale_min = self.rescale_min
                    rescale_max = self.rescale_max
                    [temp, self.image_min, self.image_max] = c_image.rescaleImage(image,
                                                                                  False,
                                                                                  False,
                                                                                  False,
                                                                                  [rescale_min, rescale_max],
                                                                                  None)
                    self.lock.release()
                    qImg = QtGui.QImage(temp.data, 2048, 2048, QtGui.QImage.Format_Indexed8)
                    pixmap01 = QtGui.QPixmap.fromImage(qImg)
                    self.ui.livewindow.setPixmap(pixmap01)
                    time.sleep(sleep_time / 1000.0)
                else:
                    break
                    # stop=time.clock()
                    # print("time for one frame display: "+str(stop-start))

    # when record button is clicked, set record flag to True or False, then record thread will start or stop

    def record_state_change(self):
        if not self.ui.recordButton.isChecked():
            self.stop_record()



        else:
            self.start_record()


    def recording(self):
        '''record child thread
        record frames when one cycle ends'''
        # start = time.clock()
        print("record thread id: " + str(threading.current_thread().name))
        for i in self.frames:
            if self.record_thread_flag == False:
                return (0)
            image = i.np_array.reshape((2048, 2048))
            self.tiff.write_image(image)#use libtiff
            #self.tiff.tinytiffwrite(image,self.file)
            #tifffile.imsave(self.filename, image) #use tifffile.py

    def start_record(self):
        self.lines.set_lines()
        #self.stage.is_stage_runing=True
        #self.lines.is_lines_runing=True
        self.filename = 'D:\\Data\\' + self.ui.name_text.text() + self.ui.name_num.text() + '.tif'
        self.ui.recordButton.setText('stop')
        #self.tiff = tinytiffwriter.tinytiffwriter()#use tinytiffwriter.dll
        #self.file = self.tiff.tinytiffopen(self.filename,16,2048,2048)
        self.ui.name_num.setValue(int(self.ui.name_num.text())+1)
        self.tiff = libtiff.TIFF.open(self.filename, mode='w8')#use libtiff
        self.record_thread_flag = True
        self.live_thread_flag=True
        self.hcam.startAcquisition()
        self.hcam.setPropertyValue('exposure_time', float(self.ui.rcam_expo.text()) / 1000.0)
        #self.get_buffer_thread = threading.Thread(target=self.buffer_thread, name='bufferThread')
        #self.get_buffer_thread.start()
        for i in range(int(float(self.ui.range.text())/float(self.ui.step.text()))):
            self.in_queue()
        self.synchronous_thread = Mythread(self.worker)

        self.get_buffer_timer = QtCore.QTimer()
        self.get_buffer_timer.timeout.connect(lambda: self.get_buffer())
        self.synchronous_thread.start()
        self.get_buffer_timer.start(1000)
        #self.start_lines_thread = threading.Thread(target=self.start_lines, name='linesThread')
        #self.start_lines_thread.start()

    def in_queue(self):
        self.queue.put({'lines':0})
        self.queue.put({'stage':float(self.ui.step.text())})

    def worker(self):
        while not self.queue.empty():
            item = self.queue.get()
            module=getattr(self, str(list(item.keys())[0]))
            module.run(item[str(list(item.keys())[0])])
            time.sleep(0.1)

    def start_lines(self):
        self.stage.signal.emit(float(self.ui.range.text()))
        print("start lines thread id: " + str(threading.current_thread().name))

    def buffer_thread(self):
        self.get_buffer_timer = QtCore.QTimer()
        self.get_buffer_timer.timeout.connect(lambda: self.get_buffer())
        self.get_buffer_timer.start(1000)
        print("buffer timer thread id: " + str(threading.current_thread().name))

    def stop_record(self):
        self.record_thread_flag = False
        self.live_thread_flat=False
        #self.stage.is_stage_runing = False
        #self.lines.is_lines_runing = False
        self.get_buffer_timer.stop()
        if self.ui.rcycles==0:
            self.lines.stop()
        self.ui.recordButton.setChecked(False)
        self.ui.recordButton.setText("record")
        try:
            self.tiff.close()#use libtiff
            #self.tiff.tinytiffclose(self.file)
        except:
            pass

    def stageUi(self):
        self.ui.message_label.setText('initializing stage Gui')
        self.stage = Stage.Stage()
        self.ui.message_label.setText('stage Gui initialized')

    def shutterUi(self):
        self.shutter = shutter.shutterGui(self.message)

    def aotfUi(self):
        self.aotf = aotfui.Aotf(self.message)

    def galvoUi(self):
        self.galvo = Galvo.Galvo(self.message)

class Mythread(threading.Thread):
    def __init__(self,func):
        super().__init__()
        self.func=func

    def run(self):
        self.func()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    example = MainWindow()
    sys.exit(app.exec_())