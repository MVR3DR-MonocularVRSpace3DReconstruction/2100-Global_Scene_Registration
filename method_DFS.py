
import os
import numpy as np

from time import time
import datetime

import math
import open3d as o3d

from deep_global_registration.core.deep_global_registration import DeepGlobalRegistration
from deep_global_registration.config import get_config

from utils import *
from colored_icp import *
from overlap import overlap_predator

data_dir = "./data/redwood-livingroom/"

def get_matching_indices(source, target, trans, search_voxel_size, K=None):
  source_copy = copy.deepcopy(source)
  target_copy = copy.deepcopy(target)
  source_copy.transform(trans)
  pcd_tree = o3d.geometry.KDTreeFlann(target_copy)

  match_inds = []
  for i, point in enumerate(source_copy.points):
    [_, idx, _] = pcd_tree.search_radius_vector_3d(point, search_voxel_size)
    if K is not None:
      idx = idx[:K]
    for j in idx:
      match_inds.append((i, j))
  return match_inds

def compute_overlap_ratio(pcd0, pcd1, trans, voxel_size):
  pcd0_down = pcd0.voxel_down_sample(voxel_size)
  pcd1_down = pcd1.voxel_down_sample(voxel_size)
  matching01 = get_matching_indices(pcd0_down, pcd1_down, trans, voxel_size, 1)
  matching10 = get_matching_indices(pcd1_down, pcd0_down, np.linalg.inv(trans), voxel_size, 1)
  overlap0 = len(matching01) / len(pcd0_down.points)
  overlap1 = len(matching10) / len(pcd1_down.points)
  return max(overlap0, overlap1)

def colored_icp_registration(source, target, voxel_size):
    # print("# Colored ICP registration")
    o3d.utility.set_verbosity_level(o3d.utility.VerbosityLevel.Warning)
    voxel_radius = [5*voxel_size, 3*voxel_size, 1.5*voxel_size]
    max_iter = [60, 35, 20]
    _transformation_cicp = np.identity(4)
    for scale in range(3):
        max_it = max_iter[scale]
        radius = voxel_radius[scale]
        # print("=> scale_level = {0}, voxel_size = {1}, max_iter = {2}".format(scale, radius, max_it))
        try:
            result = o3d.pipelines.registration.registration_colored_icp(
                source, target, radius, _transformation_cicp,
                o3d.pipelines.registration.TransformationEstimationForColoredICP(),
                o3d.pipelines.registration.ICPConvergenceCriteria(relative_fitness=1e-6,
                                                                relative_rmse=1e-6,
                                                                max_iteration=max_it))
            _transformation_cicp = result.transformation                                                    
        except Exception as e:
            # print("=> No correspondence found. ")
            continue
    return _transformation_cicp

def ransac_global_registration(source_down, target_down, voxel_size):
    distance_threshold = voxel_size * 1.5

    source_fpfh = o3d.pipelines.registration.compute_fpfh_feature(
        source_down,
        o3d.geometry.KDTreeSearchParamHybrid(radius=voxel_size * 5, max_nn=100))

    target_fpfh = o3d.pipelines.registration.compute_fpfh_feature(
        target_down,
        o3d.geometry.KDTreeSearchParamHybrid(radius=voxel_size * 5, max_nn=100))
    # print("=> voxel size: {} // distance threshold: {}".format(voxel_size, distance_threshold))
    result = o3d.pipelines.registration.registration_ransac_based_on_feature_matching(
        source_down, target_down, source_fpfh, target_fpfh, True,
        distance_threshold,
        o3d.pipelines.registration.TransformationEstimationPointToPoint(False),
        3, [
            o3d.pipelines.registration.CorrespondenceCheckerBasedOnEdgeLength(0.9),
            o3d.pipelines.registration.CorrespondenceCheckerBasedOnDistance(distance_threshold)
        ], o3d.pipelines.registration.RANSACConvergenceCriteria(100000, 0.999))
    return result.transformation

def global_registration(source, target, max_correspondence_distance_fine=0.03):
    # print("# Apply Deep Global Reg ")
    if 'DGR' not in globals():
        config = get_config()
		# best_val_checkpoint.pth  ResUNetBN2C-feat32-3dmatch-v0.05.pth   ResUNetBN2C-feat32-kitti-v0.3.pth
        config.weights = "deep_global_registration/pth/ResUNetBN2C-feat32-3dmatch-v0.05.pth"
        global DGR
        DGR = DeepGlobalRegistration(config)
    down_voxel_size = 0.05
    source_down = copy.deepcopy(source)
    target_down = copy.deepcopy(target)
    source_down.voxel_down_sample(down_voxel_size)
    target_down.voxel_down_sample(down_voxel_size)
    source_down.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=down_voxel_size*2, max_nn=30))
    target_down.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=down_voxel_size*2, max_nn=30))

    transformation_dgr, useSafeGuard = DGR.register(source_down, target_down)
    overlap_ratio = compute_overlap_ratio(source_down, target_down, transformation_dgr, down_voxel_size)
    print(f"[{overlap_ratio}]")
    
    if overlap_ratio < 0.3:
        transformation_dgr = overlap_predator(source_down, target_down)
        overlap_ratio = compute_overlap_ratio(source_down, target_down, transformation_dgr, down_voxel_size)
        print("fix to:",overlap_ratio)
    if overlap_ratio < 0.3:
        transformation_dgr = ransac_global_registration(source_down, target_down, down_voxel_size)
        overlap_ratio = compute_overlap_ratio(source_down, target_down, transformation_dgr, down_voxel_size)
        print("fix to:",overlap_ratio)
        # input()

    source_down.transform(transformation_dgr)
    
    transformation_icp = colored_icp_registration(source_down, target_down, down_voxel_size)
    
    transformation = transformation_dgr @ transformation_icp
    information = o3d.pipelines.registration.get_information_matrix_from_point_clouds(
        source_down, target_down, max_correspondence_distance_fine,
        transformation)
    # source_down.transform(transformation)
    # o3d.visualization.draw_geometries([source_down, target_down])
    return transformation, information, useSafeGuard


def pcd_fusion_dfs(_pcd_list, depth):
	n_pcds = len(_pcd_list)
	# return single pcd
	if n_pcds < 2:
		# print("="*50)
		print("  |"*(depth-1)+"---> Single Point Cloud [Returned]")
		# print("="*50)
		return _pcd_list[0]
	if n_pcds > 4:
		# get half of merged pcds
		left_pcd = pcd_fusion_dfs(_pcd_list[:n_pcds//2+1], depth+1)
		right_pcd = pcd_fusion_dfs(_pcd_list[n_pcds//2+1:], depth+1)
	else:
		# get half of merged pcds
		left_pcd = pcd_fusion_dfs(_pcd_list[:n_pcds//2], depth+1)
		right_pcd = pcd_fusion_dfs(_pcd_list[n_pcds//2:], depth+1)
	print("  |"*(depth-1)+"---> Registration..")

	T, _, _ = global_registration(left_pcd, right_pcd)
	left_pcd.transform(T)
	print("  |"*(depth-1)+"---> Merge pcds")
	merged_pcd = merge_pcds([left_pcd,right_pcd])
	# storage temp
	timestamp = int(round(time() * 1000))
	o3d.io.write_point_cloud("./outputs/dfs/D{:0>3}_L{:0>3}_{}.ply".format(depth, n_pcds, timestamp), merged_pcd)
	# o3d.visualization.draw_geometries([merged_pcd])

	# print("="*50)
	print("  |"*(depth-1)+"---> List length: {} Stack Depth: {} [Merged Complete]".format(n_pcds, depth))
	# print("="*50)
	return merged_pcd

if __name__ == '__main__':

	start_time = time()
	config = get_config()
	config.weights = "deep_global_registration/pth/ResUNetBN2C-feat32-3dmatch-v0.05.pth"
	DGR = DeepGlobalRegistration(config)

	pcds = read_point_clouds(data_dir = "outputs/",down_sample=0.02)
	
	pause_time = time()
	# o3d.visualization.draw_geometries(pcds)
	pause_time = time() - pause_time
	merged_pcd = o3d.geometry.PointCloud()
	main_pcd =  pcd_fusion_dfs(pcds, 0)


	end_time = time()
	time_cost = end_time-start_time-pause_time
	print("\n## Total cost {}s = {}m{}s.".format(
		time_cost, int((time_cost)//60), int(time_cost - (time_cost)//60*60)))
	o3d.io.write_point_cloud("./outputs/dfs/DFS-outputs.ply", main_pcd)
	o3d.visualization.draw_geometries([main_pcd])