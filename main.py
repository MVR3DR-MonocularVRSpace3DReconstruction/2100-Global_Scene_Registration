
import os
import numpy as np

import open3d as o3d
from core.deep_global_registration import DeepGlobalRegistration
from config import get_config

# generate pointcloud from RGB-D
import matplotlib.pyplot as plt
import matplotlib
from utils import *
from colored_icp import *



DATA_DIR = "./data/redwood-livingroom/"
COLOR_LIST = sorted(os.listdir(DATA_DIR+'image/'))
DEPTH_LIST = sorted(os.listdir(DATA_DIR+'depth/'))
STEP = 10

# set up matplotlib
is_ipython = 'inline' in matplotlib.get_backend()
if is_ipython:
    from IPython import display

#draw graph
plt.ion()

def plot_durations(i, y):
    plt.figure(1)
#     plt.clf() 此时不能调用此函数，不然之前的点将被清空。
    plt.subplot(111)
    plt.plot(i, y, '.')

    plt.pause(0.001)  # pause a bit so that plots are updated
    if is_ipython:
        display.clear_output(wait=True)
        display.display(plt.gcf())

if not os.path.exists(DATA_DIR):
  print('No such DIR - "'+DATA_DIR+'" !')

if __name__ == '__main__':

	config = get_config()
	if config.weights is None:
		config.weights = "./pth/ResUNetBN2C-feat32-3dmatch-v0.05.pth"
						#  "./pth/ResUNetBN2C-feat32-kitti-v0.3.pth"
						#  "./pth/ResUNetBN2C-feat32-3dmatch-v0.05.pth"
	# registration
	dgr = DeepGlobalRegistration(config)

	print("* Total "+str(len(COLOR_LIST))+" RGB-D with "+str(STEP)+" per step, needs "+str(int(len(COLOR_LIST)/STEP))+" steps")

	# METHOD-4 flex duration
	MAX_DURATION = 100
	REDUCE = 0.75

	print("=> PCD_LIST generated")
	
	curr_pcd = 0
	duration = MAX_DURATION
	REG_PCD_LIST = []

	pcd_base = generate_point_cloud(
			DATA_DIR+'image/'+COLOR_LIST[curr_pcd],
			DATA_DIR+'depth/'+DEPTH_LIST[curr_pcd]
			)
	#draw 
	X = []
	Y = []

	count = 0
	T = np.eye(4)
	while curr_pcd != len(COLOR_LIST)-1:
		print("==> Current pcd: [{}] \t Reg pcd: [{}] \tTotal pcd: [0-{}]".format(curr_pcd,curr_pcd+duration,len(COLOR_LIST)-1))
		
		#avoid endless loop
		if duration == 0:
			print("\n\n## WARNING endless loop in no valid registration")
			print("\n\n\n=> Initial new pcd list")
			curr_pcd += 10
			REG_PCD_LIST.append(pcd_base)
			pcd_base = generate_point_cloud(
				DATA_DIR+'image/'+COLOR_LIST[curr_pcd],
				DATA_DIR+'depth/'+DEPTH_LIST[curr_pcd]
				)
			# duration = MAX_DURATION
			# avoid range overflow
			if curr_pcd + MAX_DURATION <= len(COLOR_LIST)-1:
				duration = MAX_DURATION
			else:
				duration = len(COLOR_LIST)-1-curr_pcd

			# o3d.visualization.draw_geometries([pcd_base[-1],pcd_trans])
			# cin = input()
			
		# pcd_base.voxel_down_sample(0.8)
		pcd_trans = generate_point_cloud(
			DATA_DIR+'image/'+COLOR_LIST[curr_pcd+duration],
			DATA_DIR+'depth/'+DEPTH_LIST[curr_pcd+duration]
			)
		
		# preprocessing
		pcd_base.estimate_normals()
		pcd_trans.estimate_normals()

		print('=> Registration..')
		# registration
		T, isGoodReg = dgr.register(pcd_trans, pcd_base)
		if isGoodReg:
			print('=> Good Registration [v]\n\t success duration <{}> '.format(duration))
			pcd_trans.transform(T)

			pcd_base.random_down_sample(0.8)

			# color icp
			T = colored_icp(pcd_trans,pcd_base)
			pcd_trans.transform(T)

			pcd_base = merge_pcds([pcd_base,pcd_trans])
			# o3d.visualization.draw_geometries([pcd_base])

			#log
			X.append(count)
			Y.append(duration)
			# plot_durations(X, Y)


			curr_pcd += duration
			# avoid range overflow
			if curr_pcd + MAX_DURATION <= len(COLOR_LIST)-1:
				duration = MAX_DURATION
			else:
				duration = len(COLOR_LIST)-1-curr_pcd

			count += 1
			# o3d.visualization.draw_geometries([merged_pcd[-1],REG_PCD_LIST[-2]])
			
		else:
			duration = int(duration * REDUCE)
			print('=> Bad Registration [x]\n\t set duration into "{}"'.format(duration))

	plot_durations(X, Y)
	print("## {} sub list generated with".format(len(REG_PCD_LIST)))
	
	i = 0
	for pcd in REG_PCD_LIST:
		o3d.visualization.draw_geometries([pcd])
		o3d.io.write_point_cloud("./tmp/main/tmp-{:0>5}.ply".format(i), pcd)
		i += 1
