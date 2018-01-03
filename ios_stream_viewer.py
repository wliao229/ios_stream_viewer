from scene import *
from random import randint
from threading import Thread, Lock
from collections import deque

from pythonosc import dispatcher, osc_server


import ui
import time, socket
import random, math, itertools

PACKET_SAMPLE_SIZE = 200
DEVICE_IDS = ('e4f7','cec8','6b37','3fa5')

class Series(ShapeNode):
	def __init__(self, name, bsize, line_color, color, *args, **kwargs):
		self.bsize = bsize
		border = ui.Path.rect(0,0, self.bsize.w, self.bsize.h)
		ShapeNode.__init__(self, border, *args, **kwargs)

		self.lines = deque()
		self.buffer = [0]
		self.line_color = line_color
		self.color = color
		self.bufferLength = 201

		# label channel
		self.label = LabelNode(name, position=(self.bsize.w - 2 , self.bsize.h), 
			font = ('Helvetica', 12), color = 'black', parent = self, anchor_point = (1,1))
		
		# grid 
		self.grids = [
		ShapeNode(ui.Path.rect(0, 0, self.bsize.w, self.bsize.h/2), 		
				stroke_color = 'black', fill_color='clear',
				parent = self, anchor_point = (0,0)),
		ShapeNode(ui.Path.rect(0, 0, self.bsize.w, 	self.bsize.h/2), 
			stroke_color = 'black', fill_color='clear',
			position=(0, self.bsize.h/2),
				parent = self, anchor_point = (0,0))
				]
	
	def trim(self, y):
		if y <= -self.bsize.h / 2 + 2:
			return -self.bsize.h / 2 + 2
		if y >= self.bsize.h / 2 :
			return self.bsize.h / 2
		return y
		
	def update(self):			
		while len(self.buffer) > self.bufferLength:
			data = self.buffer[:self.bufferLength]
			del self.buffer[:self.bufferLength - 1]
			
			if len(self.lines) == 0:
				last_line_x_end = self.bsize.w + self.bufferLength * self.scene.timeScale
			else:
				last_line_x_end = self.lines[-1].position.x + self.bufferLength * self.scene.timeScale	
				# drop the oldest line & update valScale
				if self.lines[0].position.x < 0:
					first_line = self.lines.popleft()
					first_line.remove_from_parent()
			

			### append a new line
			path = ui.Path()
			
			# draw upper bound
			path.move_to(0, -self.bsize.h / 2 - 4)
			path.line_to(self.bufferLength * self.scene.timeScale, -self.bsize.h / 2 - 4)
			
			# draw waveform
			if data[0]:
				y0 = self.trim(data[0] * self.scene.valueScale * self.bsize.h)
				path.move_to(0, y0)			
				isLastNone = False	
			else:
				isLastNone = True

			for x,y in enumerate(data):
				if y:
					y = self.trim(y * self.scene.valueScale * self.bsize.h)
					if isLastNone:
						path.move_to(x * self.scene.timeScale, y)		
					else:
						path.line_to(x * self.scene.timeScale, y)
					isLastNone = False
				else:
					isLastNone = True

			path.line_width = 1
			new_line = ShapeNode(path, 
				parent=self,
				stroke_color= self.line_color,
				fill_color='clear', 
				position=(last_line_x_end - 1 * self.scene.timeScale, self.bsize.h + 6),
				anchor_point=(1,1)
			)
				
			self.lines.append(new_line)
			
		if len(self.lines) > 0:
			return(self.bsize.w - self.lines[-1].position.x) 
		else:
			return(0)
			
class Viewer(Scene):
	def __init__(self, device_ids, nChannel, server, lock, *args, **kwargs):
		Scene.__init__(self, *args, **kwargs)
		self.server = server
		self.device_ids = device_ids
		self.nChannel = nChannel
		self.lock = lock

		self.sampleCounters = dict(zip(device_ids, [0]*len(device_ids)))
		self.prevSampleIndex = dict(zip(device_ids, [0]*len(device_ids)))
		self.devices = dict(zip(device_ids, [None]*len(device_ids)))
		self.masks = dict(zip(device_ids, [None]*len(device_ids)))
		self.deviceLabels = dict(zip(device_ids, [None]*len(device_ids)))
		self.deviceStatusLabels = dict(zip(device_ids, [None]*len(device_ids)))

		self.prevTouch = None
		self.isRunning = True
		self.prevSampleSecond = self.t
		self.timeScale = .5
		self.valueScale = -300
		self.runningSamples = dict(zip(device_ids, [deque([],10) for i in device_ids])) 
		
	def touch_began(self, touch):
		self.isRunning = False
	
	def touch_ended(self, touch):
		self.isRunning = True
	
	def did_change_size(self):
		screen_size = get_screen_size()
		
		for i, id in enumerate(self.devices):
			if screen_size.w > screen_size.h:
				mask_size = Size(screen_size.w / len(self.devices) + 1, screen_size.h)
				mask_position = Point(i * screen_size.w / len(self.devices), 0)
				self.deviceLabels[id].position = (mask_position.x + 4, mask_size.h - 1)
				self.deviceStatusLabels[id].position = (mask_position.x + 2, 2)
			else:
				mask_size = Size(screen_size.w , screen_size.h / len(self.devices) + 1)
				mask_position = Point(0, i * screen_size.h / len(self.devices))
				self.deviceLabels[id].position = (mask_position.x + 4, (i+1)*mask_size.h - 1)					
				self.deviceStatusLabels[id].position =(mask_position.x + 2, i*mask_size.h + 2)
			
			# update mask
			self.masks[id].size = mask_size
			self.masks[id].crop_rect = Rect(mask_position.x, mask_position.y,	
				mask_size.w+1, mask_size.h)
			
			# update series
			for j, series in enumerate(self.devices[id]) :
				if screen_size.w > screen_size.h:
					series_size = Size(screen_size.w / len(self.devices) - 1, 
						screen_size.h / self.nChannel - 1)
					series_pos = Point(i * screen_size.w / len(self.devices), 
						j * screen_size.h / self.nChannel)
				else:
					series_size = Size(screen_size.w , 
						screen_size.h / ( self.nChannel * len(self.devices)) - 1)
					series_pos = Point(0, 
						i * screen_size.h / len(self.devices) + j * screen_size.h / (self.nChannel * len(self.devices))
						)			
				series.bsize = series_size
				series.maxLines = series.bsize.w / series.bufferLength / series.scene.timeScale 
				series.position = series_pos	
				series.path = ui.Path.rect(0,0, series_size.w, series_size.h)
				series.grids[0].path = ui.Path.rect(0, 0, series_size.w, 	series_size.h/2)
				series.grids[1].path = ui.Path.rect(0, 0, series_size.w, 	series_size.h/2)
				series.grids[1].position = (0, series_size.h/2)
				series.label.position = (series.bsize.w - 2 , series.bsize.h)
				
				for line in series.lines:
					line.remove_from_parent()
				
				series.lines.clear()
			
	def setup(self):		
		fill_colors = ('grey','darkgray','grey','darkgray')
		line_colors = ('lightgreen','lightblue','lightpink','lightyellow')
		colors = ('darkgreen', 'darkblue', 'darkred', 'darkorange')
				
		screen_size = get_screen_size()

		for i, id in enumerate(self.device_ids):

			# Mask Node (Device Window)			
			mask = EffectNode(parent = self)
			label = LabelNode('Device {}'.format(id), 
				font = ('Helvetica', 12), color = 'black',
				anchor_point=(0,1), z_position = 2, parent= mask
				)
			status_label = LabelNode('', font = ('Helvetica', 12), 
					anchor_point=(0,0), z_position = 2, parent=mask
				)
			if screen_size.w > screen_size.h:
				mask_size = Size(screen_size.w / len(self.devices) + 1, screen_size.h)
				mask_position = Point(i * screen_size.w / len(self.devices) , 0)
				label.position= (mask_position.x + 4, mask_size.h - 1)					
				status_label.position=(mask_position.x + 2, 2)
			else:
				mask_size = Size(screen_size.w , screen_size.h / len(self.devices)  + 1)
				mask_position = Point(0, i * screen_size.h / len(self.devices) )
				label.position= (mask_position.x + 4, (i+1)*mask_size.h - 1)					
				status_label.position=(mask_position.x + 2, i*mask_size.h + 2)
				
			mask.crop_rect = Rect(mask_position.x, mask_position.y,	
				mask_size.w+1, mask_size.h)						
				
			self.masks[id] = mask			
			self.deviceLabels[id] = label
			self.devices[id] = list()
			self.deviceStatusLabels[id] = status_label
			
			for j in range(self.nChannel):
				if screen_size.w > screen_size.h:
					series_size = Size(screen_size.w / len(self.devices)  - 1, 
						screen_size.h / self.nChannel - 1)
					series_pos = Point(i * screen_size.w / len(self.devices) , 
						j * screen_size.h / self.nChannel)
				else:
					series_size = Size(screen_size.w , 
						screen_size.h / ( self.nChannel * len(self.devices) ) - 1)
					series_pos = Point(0, i * screen_size.h / len(self.devices)  + 
						j * screen_size.h / (self.nChannel * len(self.devices) ))			
				
				series = Series(
					name = 'Channel {}'.format(j+1),
					bsize=series_size,
					position=series_pos,
					anchor_point=(0,0),
					line_color = 'white', #line_colors[j],
					color = 'white', #colors[j], 
					stroke_color = 'clear', 
					fill_color = fill_colors[i],
					z_position=0,
					parent=mask)

				self.devices[id].append(series)

	def update(self):
			duration = self.t - self.prevSampleSecond
			if duration >= 1:
				for i, id in enumerate(self.devices):					
					self.lock.acquire()					
					sampleCount = self.sampleCounters[id]
					for series in self.devices[id]:
						deltaX = series.update()
						move_by = Action.move_by(deltaX, 0, duration)							
				
						for line in series.lines:				
							line.run_action(move_by)
					self.lock.release()
					
						
					self.runningSamples[id].append(sampleCount)					
					averageSampleRate = sum(self.runningSamples[id])/len(self.runningSamples[id])
				
					self.deviceStatusLabels[id].text = '{:.0f}Hz {:.0f}Hz(10s)'.format(sampleCount, averageSampleRate)

					self.lock.acquire()		
					self.sampleCounters[id] = 0
					self.lock.release()

	
				self.prevSampleSecond = self.t
			
			
	def stop(self):

		self.server.shutdown()
		self.server.server_close()
		print('server shuntdown.')
	
def raw_osc_handler(unused_addr, *args):

	global viewer
	global lock
	
	id = args[0][0] # device index
	msg = args[1:]	
#	print(msg[0])
	try:
		device = viewer.devices[id]
		assert len(msg) == 5, 'wrong message length: {}'.format(msg) 
		dropCount = 0
		sampleIndex = msg[0]
		sample = msg[1:]
		if sampleIndex - viewer.prevSampleIndex[id] != 1:
			if sampleIndex != 0:
				if sampleIndex < viewer.prevSampleIndex[id]:
					dropCount = sampleIndex + 200 - viewer.prevSampleIndex[id]
				else:
					dropCount = sampleIndex - viewer.prevSampleIndex[id]	

		viewer.prevSampleIndex[id] = sampleIndex	
		
		lock.acquire()
		viewer.sampleCounters[id] += 1 + dropCount

		for j, series in enumerate(device):
			series.buffer.extend([None] * dropCount)
			series.buffer.append(sample[j])
		
		lock.release()
				

	except Exception as e:
		print('error in parsing osc message: {!s}. {}'.format(e, msg))

def switched(sender):
	global used_device_ids
	
	if sender.value:
		used_device_ids.add(sender.device_id)
	else:
		used_device_ids.discard(sender.device_id)
	
def start_viewer(sender):
	global viewer

	### OSC Server ###
	local_address = socket.gethostbyname(socket.gethostname())
	dispatch = dispatcher.Dispatcher()
	
	for i, id in enumerate(used_device_ids):
		dispatch.map('/{}'.format(id), raw_osc_handler, id)

	server = osc_server.ThreadingOSCUDPServer((local_address, 5005), dispatch)
	server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 512000)
	server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVLOWAT, 1)

	viewer = Viewer(device_ids=used_device_ids, nChannel=4, server=server, lock=lock)
	
	### START SERVER ###	
	server_thread = Thread(target=server.serve_forever)
	server_thread.setDaemon(True)
	server_thread.start()
	print('serving at {}:{}'.format(local_address, 5005))

		
	sceneView = SceneView()
	sceneView.scene = viewer
	sceneView.flex = 'LRHWT' 
	sceneView.present('full_screen')
			
if __name__ == '__main__':
	used_device_ids = set(('e4f7','cec8'))
	lock = Lock()

	### UI Viewer ###
	v = ui.load_view('stream_viewer.pyui')
	v.present(style='full_screen')	
	### Visualization Starts ####
	#run(viewer, show_fps = True, frame_interval = 1, anti_alias = True)
	
