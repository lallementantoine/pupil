import cv2
import numpy as np
from gl_utils import draw_gl_polyline,adjust_gl_view,clear_gl_screen
import atb
import audio
from ctypes import c_int,c_bool
import OpenGL.GL as gl
from glfw import *


from plugin import Plugin

# def calbacks
def on_resize(window,w, h):
    glfwMakeContextCurrent(window)
    adjust_gl_view(w,h)



class Camera_Intrinsics_Estimation(Plugin):
    """Camera_Intrinsics_Calibration
        not being an actual calibration,
        this method is used to calculate camera intrinsics.

    """
    def __init__(self,g_pool,atb_pos=(0,0)):
        Plugin.__init__(self)
        self.collect_new = False
        self.calculated = False
        self.obj_grid = _gen_pattern_grid((4, 11))
        self.img_points = []
        self.obj_points = []
        self.count = 10
        self.img_shape = None


        self._window = None
        self.fullscreen = c_bool(1)
        self.monitor_idx = c_int(0)
        self.monitor_handles = glfwGetMonitors()
        self.monitor_names = [glfwGetMonitorName(m) for m in self.monitor_handles]
        monitor_enum = atb.enum("Monitor",dict(((key,val) for val,key in enumerate(self.monitor_names))))
        #primary_monitor = glfwGetPrimaryMonitor()

        atb_label = "estimate camera instrinsics"
        # Creating an ATB Bar is required. Show at least some info about the Ref_Detector
        self._bar = atb.Bar(name =self.__class__.__name__, label=atb_label,
            help="ref detection parameters", color=(50, 50, 50), alpha=100,
            text='light', position=atb_pos,refresh=.3, size=(300, 100))
        self._bar.add_var("monitor",self.monitor_idx, vtype=monitor_enum)
        self._bar.add_var("fullscreen", self.fullscreen)
        self._bar.add_button("  show pattern   ", self.open_window, key='c')
        self._bar.add_button("  Capture Pattern", self.advance, key="SPACE")
        self._bar.add_var("patterns to capture", getter=self.get_count)

    def get_count(self):
        return self.count

    def advance(self):
        if self.count ==10:
            audio.say("Capture 10 calibration patterns.")
        self.collect_new = True

    def open_window(self):
        if self.fullscreen.value:
            monitor = self.monitor_handles[self.monitor_idx.value]
            mode = glfwGetVideoMode(monitor)
            height,width= mode[0],mode[1]
        else:
            monitor = None
            height,width= 640,360

        self._window = glfwCreateWindow(height, width, "Calibration", monitor=monitor, share=None)
        if not self.fullscreen.value:
            glfwSetWindowPos(self._window,200,0)

        on_resize(self._window,height,width)

        #Register callbacks
        glfwSetWindowSizeCallback(self._window,on_resize)
        glfwSetWindowCloseCallback(self._window,self.close_window)
        glfwSetKeyCallback(self._window,self.on_key)
        # glfwSetCharCallback(self._window,on_char)

        # gl_state settings
        active_window = glfwGetCurrentContext()
        glfwMakeContextCurrent(self._window)
        gl.glEnable(gl.GL_POINT_SMOOTH)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        gl.glEnable(gl.GL_BLEND)
        gl.glClearColor(1.,1.,1.,0.)
        glfwMakeContextCurrent(active_window)

    def close_window(self,window):
        glfwDestroyWindow(self._window)
        self._window = None

    def on_key(self,window, key, scancode, action, mods):
        if not atb.TwEventKeyboardGLFW(key,int(action == GLFW_PRESS)):
            if action == GLFW_PRESS:
                if key == GLFW_KEY_ESCAPE or GLFW_KEY_C:
                    self.close_window(window)




    def calculate(self):
        self.calculated = True
        camera_matrix, dist_coefs = _calibrate_camera(np.asarray(self.img_points),
                                                    np.asarray(self.obj_points),
                                                    (self.img_shape[1], self.img_shape[0]))
        np.save("camera_matrix.npy", camera_matrix)
        np.save("dist_coefs.npy", dist_coefs)
        audio.say("Camera calibrated and saved to file")

    def update(self,frame,recent_pupil_positions):
        if self.collect_new:
            img = frame.img
            status, grid_points = cv2.findCirclesGridDefault(img, (4,11), flags=cv2.CALIB_CB_ASYMMETRIC_GRID)
            if status:
                self.img_points.append(grid_points)
                self.obj_points.append(self.obj_grid)
                self.collect_new = False
                self.count -=1
                if self.count in range(1,10):
                    audio.say("%i" %(self.count))
                self.img_shape = img.shape

        if not self.count and not self.calculated:
            self.calculate()

    def gl_display(self):
        """
        use gl calls to render
        at least:
            the published position of the reference
        better:
            show the detected postion even if not published
        """
        for grid_points in self.img_points:
            calib_bounds =  cv2.convexHull(grid_points)[:,0] #we dont need that extra encapsulation that opencv likes so much
            draw_gl_polyline(calib_bounds,(0.,0.,1.,.5), type="Loop")

        if self._window:
            self.gl_display_in_window()

    def gl_display_in_window(self):
        pass


    def cleanup(self):
        """gets called when the plugin get terminated.
        This happends either volunatily or forced.
        if you have an atb bar or glfw window destroy it here.
        """
        if self._window:
            self.close_window(self._window)

        if hasattr(self,"_bar"):
                try:
                    self._bar.destroy()
                    del self._bar
                except:
                    print "Tried to delete an already dead bar. This is a bug. Please report"


# shared helper functions for detectors private to the module
def _calibrate_camera(img_pts, obj_pts, img_size):
    # generate pattern size
    camera_matrix = np.zeros((3,3))
    dist_coef = np.zeros(4)
    rms, camera_matrix, dist_coefs, rvecs, tvecs = cv2.calibrateCamera(obj_pts, img_pts,
                                                    img_size, camera_matrix, dist_coef)
    return camera_matrix, dist_coefs

def _gen_pattern_grid(size=(4,11)):
    pattern_grid = []
    for i in xrange(size[1]):
        for j in xrange(size[0]):
            pattern_grid.append([(2*j)+i%2,i,0])
    return np.asarray(pattern_grid, dtype='f4')