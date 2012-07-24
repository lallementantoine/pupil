import glumpy 
import OpenGL.GL as gl
import OpenGL.GLUT as glut
import glumpy.atb as atb
from ctypes import c_int,c_bool,c_float
import cPickle as pickle
import numpy as np

from time import sleep


from methods import *
from calibrate import *
from gl_shapes import Point, Ellipse
from methods import Temp,capture
from multiprocessing import Queue, Value

class Bar(atb.Bar):
	"""docstring for Bar"""
	def __init__(self, name,g_pool, defs):
		super(Bar, self).__init__(name,**defs) 
		self.fps = 0.0 
		self.sleep = c_float(0.0)
		self.display = c_int(1)
		self.pupil_point = c_bool(1)
		self.exit = c_bool(0)
		self.draw_roi = c_bool(0)
		self.bin_thresh = c_int(60)
		self.pupil_ratio = c_float(.6)
		self.pupil_size = c_float(80.)
		self.pupil_size_tolerance = c_float(40.)
		self.canny_apture = c_int(7)
		self.canny_thresh = c_int(200)
		self.canny_tolerance = c_int(10)


		#add class field here and it will become session persistant
		self.session_save = {'sleep':self.sleep,
							'display':self.display,
							'pupil_point':self.pupil_point,
							'bin_thresh':self.bin_thresh,
							'pupil_ratio':self.pupil_ratio,
							'pupil_size':self.pupil_size,
							'pupil_size_tolerance':self.pupil_size_tolerance,
							'canny_apture':self.canny_apture,
							'canny_thresh':self.canny_thresh,
							'canny_tolerance':self.canny_tolerance}

		self.load()
		
		self.add_var("Display/FPS", step=0.1, getter=self.get_fps)
		self.add_var("Display/SlowDown",self.sleep, step=0.01,min=0.0)
		self.add_var("Display/Mode", self.display, step=1,max=4, min=0, help="select the view-mode")
		self.add_var("Display/Show_Pupil_Point", self.pupil_point)		
		self.add_var("Display/Draw_ROI", self.draw_roi, help="drag on screen to select a region of interest")		
		self.add_var("Bin/Threshold", self.bin_thresh, step=1, max=256, min=0)
		self.add_var("Pupil/Ratio", self.pupil_ratio, step=.05, max=1., min=0.)
		self.add_var("Pupil/Size", self.pupil_size, step=1, min=0)
		self.add_var("Pupil/Size_Tolerance", self.pupil_size_tolerance, step=1, min=0)
		self.add_var("Canny/Apture",self.canny_apture, step=2, max=7, min=1)
		self.add_var("Canny/Edge_Threshold", self.canny_thresh, step=1,min=1)
		self.add_var("Canny/Tolerance", self.canny_tolerance, step=1,min=1)
		self.add_var("SaveSettings&Exit", g_pool.quit)



	def update_fps(self, dt):
		temp_fps = 1/dt
		self.fps += 0.1*(temp_fps-self.fps)

	def get_fps(self):
		return self.fps

	def save(self):
		new_settings = dict([(key,field.value) for key, field in self.session_save.items()])
		settings_file = open('session_settings','wb')
		pickle.dump(new_settings,settings_file)
		settings_file.close


	def load(self):
		try:
			settings_file = open('session_settings','rb')
			new_settings = pickle.load(settings_file)
			settings_file.close
		except IOError:
			print "No session_settings file found. Using defaults"
			return

		for key,val in new_settings.items():
			try:
				self.session_save[key].value = val
			except KeyError:
				print "Warning the Sessions file is from a different version, not all fields may be updated"

class Roi(object):
	"""this is a simple Region of Interest class
	it is applied on numpy arrays for convinient slicing
	like this:
	roi_array_slice = full_array[r.lY:r.uY,r.lX:r.uX]
	"""
	def __init__(self, array_shape):
		self.array_shape = array_shape
		self.lX = 0
		self.lY = 0
		self.uX = array_shape[1]-0
		self.uY = array_shape[0]-0
		self.nX = 0
		self.nY = 0

	def setStart(self,(x,y)):
		x,y = max(0,x),max(0,y)
		self.nX,self.nY = x,y

	def setEnd(self,(x,y)):
			x,y = max(0,x),max(0,y)
			if x != self.nX and y != self.nY:
				self.lX = min(x,self.nX)
				self.lY = min(y,self.nY)
				self.uX = max(x,self.nX)
				self.uY = max(y,self.nY)		

	def add_vector(self,(x,y)):
		"""
		adds the roi offset to a len2 vector
		"""
		return (self.lX+x,self.lY+y)


def eye(src, g_pool):
	"""eye
		- Initialize glumpy figure, image, atb controls
		- Execute the glumpy main glut loop
	"""
	#init capture, initialize glumpy, map img_arr to opengl texture 
	cap = capture(src,(640,320))
	s, img_arr = cap.read_RGB()

	fig = glumpy.figure((img_arr.shape[1], img_arr.shape[0]))
	image = glumpy.Image(img_arr)
	image.x, image.y = 0,0


	# pupil object
	pupil = Temp()
	pupil.norm_coords = (0,0)
	pupil.image_coords = (0,0)
	pupil.screen_coords = (0,0)
	pupil.ellipse = None
	pupil.map_coords = (0,0)
	pupil.coefs = None
	pupil.pt_cloud = None

	r = Roi(img_arr.shape)
	
	# local object
	l_pool = Temp()
	l_pool.calib_running = False
	l_pool.record_running = False
	l_pool.record_positions = []
	l_pool.record_path = None

	# initialize gl shape primitives
	pupil_point = Point()
	pupil_ellipse = Ellipse()

	atb.init()
	bar = Bar("Eye",g_pool, dict(label="Controls",
			help="Scene controls", color=(50,50,50), alpha=50,
			text='light', position=(10, 10), size=(200, 250)) )



	def on_idle(dt):
		bar.update_fps(dt)
		
		s,img = cap.read_RGB()
 		sleep(bar.sleep.value)
		###IMAGE PROCESSING 
		gray_img = grayscale(img[r.lY:r.uY,r.lX:r.uX])
		# spec_img = erase_specular(gray_img, 250,256)
		binary_img = bin_thresholding(gray_img,image_upper=bar.bin_thresh.value)
		kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7,7))
		binary_img = cv2.dilate(binary_img, kernel, iterations=3)
	

		spec_mask = cv2.inRange(gray_img, np.asarray(0.),np.asarray(250.0))
		kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7,7))
		spec_mask = cv2.erode(spec_mask, kernel, iterations=1)

		edges =  cv2.Canny(gray_img,bar.canny_thresh.value*10, bar.canny_thresh.value*10-bar.canny_tolerance.value*10,apertureSize= bar.canny_apture.value) 
		edges = cv2.min(edges, spec_mask) 
		result = fit_ellipse(edges,binary_img,bar.bin_thresh.value, ratio=bar.pupil_ratio.value,target_size=bar.pupil_size.value,size_tolerance=bar.pupil_size_tolerance.value)
		
		overlay_b = cv2.max(edges,gray_img)
		overlay =cv2.cvtColor(overlay_b, cv2.COLOR_GRAY2RGB)
		overlay[:,:,2] = cv2.max(overlay_b,binary_img)
		if result is not None:
			pupil.ellipse, others= result
			for pre,((x,y),axs,ang) in others:
				x,y = int(x),int(y)
				overlay[y,x,:]   = [0,255,0]
				# overlay[y,x+1,:] = [0,255,0]
				# overlay[y+1,x,:] = [0,255,0]
				# overlay[y+1,x+1,:]=[0,255,0]

		if bar.display.value == 0:
			img_arr[...] = img
		elif bar.display.value == 1:
			img_arr[r.lY:r.uY,r.lX:r.uX]=  np.dstack((gray_img,gray_img,gray_img))
		elif bar.display.value == 2:
			img_arr[r.lY:r.uY,r.lX:r.uX] = np.dstack((spec_mask, spec_mask, spec_mask))
		elif bar.display.value == 3:
			img_arr[r.lY:r.uY,r.lX:r.uX] = np.dstack((binary_img, binary_img, binary_img))
		else:
			img_arr[r.lY:r.uY,r.lX:r.uX] = overlay
	
		if result is not None:
			pupil.image_coords = r.add_vector(pupil.ellipse['center'])

			#update pupil size for the ellipse fiter algorithm
			bar.pupil_size.value = bar.pupil_size.value + .3*(pupil.ellipse['major']-bar.pupil_size.value)

			
			# numpy array wants (row,col) for an image this = (height,width)
			# therefore: img.shape[1] = xval, img.shape[0] = yval
			pupil.norm_coords = normalize(pupil.image_coords, img.shape[1], img.shape[0])
			pupil.screen_coords = denormalize(pupil.norm_coords, fig.width, fig.height)
			pupil_point.update(pupil.screen_coords)
			pupil_ellipse.update(pupil.screen_coords, pupil.ellipse)

			# for the world screen
			pupil.map_coords = map_vector(pupil.norm_coords, pupil.coefs)
			g_pool.pupil_x.value, g_pool.pupil_y.value = pupil.map_coords
		else:
			pupil.ellipse = None

		###CALIBRATION and MAPPING###
		# Initialize Calibration (setup variables and lists)
		if g_pool.calibrate.value and not l_pool.calib_running:
			l_pool.calib_running = True
			pupil.pt_cloud = [] 
			pupil.coefs = None

		# While Calibrating... 
		if l_pool.calib_running and (g_pool.pattern_x.value or g_pool.pattern_y.value) and pupil.ellipse:
			pupil.pt_cloud.append([pupil.norm_coords[0],pupil.norm_coords[1],
								g_pool.pattern_x.value, g_pool.pattern_y.value])

		# Calculate coefs
		if not g_pool.calibrate.value and l_pool.calib_running:         
			l_pool.calib_running = 0
			if pupil.pt_cloud:
				pupil.coefs = calibrate_poly(pupil.pt_cloud)

		
		###RECORDING###
		# Setup variables and lists for recording
		if g_pool.pos_record.value and not l_pool.record_running:
			l_pool.record_path = g_pool.eye_rx.recv()
			print "l_pool.record_path: ", l_pool.record_path
			l_pool.record_positions = []
			l_pool.record_running = True

		# While recording... 
		if l_pool.record_running:
			l_pool.record_positions.append([pupil.map_coords[0], pupil.map_coords[1], dt, g_pool.frame_count_record.value])

		# Save values and flip switch to off for recording
		if not g_pool.pos_record.value and l_pool.record_running:
			np.save(l_pool.record_path, np.asarray(l_pool.record_positions))
			l_pool.record_running = False


		image.update()
		fig.redraw()
		
		if g_pool.quit.value:
			print "EYE Process closing from global or atb"
			bar.save()
			fig.window.stop()

	
	def on_draw():
		fig.clear(0.0, 0.0, 0.0, 1.0)
		image.draw(x=image.x, y=image.y, z=0.0, 
					width=fig.width, height=fig.height)
		
		if bar.pupil_point and pupil.ellipse:
			pupil_point.draw()
			pupil_ellipse.draw()


	def on_close():
		bar.save()
		g_pool.quit.value = True
		print "EYE Process closed from window"

	def on_mouse_press(x, y, button):
		x,y = denormalize(normalize((x,y),fig.width,fig.height),img_arr.shape[1],img_arr.shape[0],flip_y=True) 
		if bar.draw_roi.value:
			r.setStart((x,y))
			
	def on_mouse_drag(x, y, dx, dy, buttons):
		x,y = denormalize(normalize((x,y),fig.width,fig.height),img_arr.shape[1],img_arr.shape[0],flip_y=True) 
		if bar.draw_roi.value:
			r.setEnd((x,y))

	fig.window.push_handlers(on_idle)
	fig.window.push_handlers(atb.glumpy.Handlers(fig.window))
	fig.window.push_handlers(on_draw)
	fig.window.push_handlers(on_mouse_press,on_mouse_drag)
	fig.window.push_handlers(on_close)	
	fig.window.set_title("Eye")
	fig.window.set_position(650,0)    
	glumpy.show()   




