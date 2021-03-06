# Thomas Macrina

# Reimplementing the elastic layer aligner from TrakEM2
# Based on source code:
# https://github.com/trakem2/TrakEM2/blob/master/TrakEM2_/src/main/java/mpicbg/trakem2/align/ElasticLayerAlignment.java

import os
import csv
import threading
import time

from ij import IJ
from ij.gui import GenericDialog
from ini.trakem2 import Project
from ini.trakem2.display import Layer
from ini.trakem2.display import LayerSet
from ini.trakem2.display import Patch
from ini.trakem2.display import VectorData
from ini.trakem2.utils import AreaUtils
from ini.trakem2.utils import Filter
from ini.trakem2.utils import Utils

from java.awt import Rectangle
from java.awt.geom import Area
from java.awt.geom import Path2D
from java.io import Serializable
from java.util import ArrayList
from java.util import Collection
from java.util import HashSet
from java.util import Iterator
from java.util import List
from java.util import Set

from mpicbg.imagefeatures import Feature
from mpicbg.imagefeatures import FloatArray2DSIFT
from mpicbg.models import AbstractModel
from mpicbg.models import AffineModel2D
from mpicbg.models import HomographyModel2D
from mpicbg.models import NotEnoughDataPointsException
from mpicbg.models import Point
from mpicbg.models import PointMatch
from mpicbg.models import RigidModel2D
from mpicbg.models import SimilarityModel2D
from mpicbg.models import Spring
from mpicbg.models import SpringMesh
from mpicbg.models import Tile
from mpicbg.models import TileConfiguration
from mpicbg.models import Transforms
from mpicbg.models import TranslationModel2D
from mpicbg.models import Vertex
from mpicbg.models import CoordinateTransform
from mpicbg.trakem2.transform import MovingLeastSquaresTransform2
from mpicbg.trakem2.util import Triple
from mpicbg.trakem2.align.Util import applyLayerTransformToPatch

from java.util.concurrent import Callable
from java.util.concurrent import Executors, TimeUnit

# See line 77 of ElasticLayerAlignment.java
LAYER_SCALE = 1.0
RESOLUTION = 32
STIFFNES = 0.1
DAMP = 0.9
MAX_STRETCH = 2000.0
MAX_ITERATIONS = 1000 #1000
MAX_PLATEAU_WIDTH = 200
MAX_EPSILON = 6
MIN_NUM_MATCHES = 1 # minimum for TranslationModel2D()
MAX_NUM_THREADS = 40
# use_legacy_optimizer = True
# desired_model_index = 1 # 0: Translation, 1: Rigid, 2: Similarity, 3: Affine

class PatchTransform(Callable):
	def __init__(self, patch, transform):
		self.patch = patch
		self.transform = transform
		self.started = None
		self.completed = None
		self.thread_used = None
		self.exception = None

	def call(self):
		self.thread_used = threading.currentThread().getName()
		self.started = time.time()
		try:
			applyLayerTransformToPatch(self.patch, self.transform)
			print self.patch.getTitle() + " patch transformed\n"
		except Exception, ex:
			self.exception = ex
			print str(ex)
			IJ.log(str(ex))
		self.completed = time.time()
		return self

def shutdown_and_await_termination(pool, timeout):
	pool.shutdown()
	try:
		if not pool.awaitTermination(timeout, TimeUnit.SECONDS):
			pool.shutdownNow()
			if (not pool.awaitTermination(timeout, TimeUnit.SECONDS)):
				print >> sys.stderr, "Pool did not terminate"
	except InterruptedException, ex:
		# (Re-)Cancel if current thread also interrupted
		pool.shutdownNow()
		# Preserve interrupt status
		threading.currentThread().interrupt()

def parse_filename_into_sections(file):
	split_name = file.split('_')
	a = int(split_name[5]) - 1
	b = int(split_name[0]) - 1
	return a, b

# Pulled from latest AreaUtils (not in legacy Fiji)
def infinite_area():
	path = Path2D.Double()
	path.moveTo(Double.MAX_VALUE, Double.MAX_VALUE)
	path.lineTo(-Double.MAX_VALUE, Double.MAX_VALUE)
	path.lineTo(-Double.MAX_VALUE, -Double.MAX_VALUE)
	path.lineTo(Double.MAX_VALUE, -Double.MAX_VALUE)
	path.lineTo(Double.MAX_VALUE, Double.MAX_VALUE)
	return Area(path)

# Pulled from latest Utils (not in legacy Fiji)
def cast_collection(current_collection, cast_type, do_throw):
	casted_collection = ArrayList()
	for a in current_collection:
		try:
			casted_collection.add(cast_type(a))
		except ClassCastException, cce:
			if do_throw:
				print cce
	return casted_collection

def get_bounding_box(layers):
	box = None
	for layer in layers:
		if box is None:
			box = layer.getMinimalBoundingBox(Patch, True)
		else:
			box = box.union(layer.getMinimalBoundingBox(Patch, True))
	return box

def create_tile_collection(layers):
	tiles = ArrayList()
	for layer in layers:
		tiles.add(Tile(RigidModel2D()))
	return tiles

def test():
	pts_reader = [[1.0,2.0,2.0,3.5],
		[0.5,2.0,1.0,3.5],
		[1.5,4.0,0.3,2.4],
		[2.0,4.5,2.0,4.5],
		[3.5,4.0,1.0,2.5]]
	meshes = ArrayList()
	for layer in layers:
		meshes.add(SpringMesh(2, 2, 4, 4, 0.9, 10, 0.6))
	return meshes, pts_reader

def create_meshes(layers, box):
	mesh_width = 16 #int(Math.ceil(box.width * LAYER_SCALE))
	mesh_height = 16 #int(Math.ceil(box.height * LAYER_SCALE))
	meshes = ArrayList()
	for layer in layers:
		meshes.add(SpringMesh(RESOLUTION,
								mesh_width,
								mesh_height,
								STIFFNES,
								MAX_STRETCH * LAYER_SCALE,
								DAMP))
	return meshes

# def main(project, directory):

# project = Project.getProject('stack_import.xml')
project = Project.getProject('turtle_rigid.xml')
# directory = '~/seungmount/research/tommy/150502_piriform/affine_block_matching/'
directory = '/usr/people/tmacrina/seungmount/research/tommy/trakem_tests/150703_elastic_redux/block_matching/'

layerset = project.getRootLayerSet()
layers = layerset.getLayers()
tiles = create_tile_collection(layers)
box = get_bounding_box(layers)
# meshes = create_meshes(layers, box)
meshes, pts_reader = test()
init_meshes = TileConfiguration()
init_meshes.fixTile(tiles[0])

# Cycle through points files to apply forces to meshes
for file in os.listdir(directory):
	if file.endswith("pre_smooth_pts.txt"):
		secA, secB = parse_filename_into_sections(file)
		spring_constant = 1.0 / (secB - secA)
		mesh = meshes.get(secB)

		pts_list = ArrayList()

		pts_file = open(directory + file)
		pts_reader = csv.reader(pts_file, delimiter=',', lineterminator='\n')
		for row in pts_reader:
			row = [float(i) for i in row]
			v1 = Vertex(row[:2], row[2:4]) # local coords, global coords
			v2 = Vertex(row[4:6], row[6:])
			v1.addSpring(v2, Spring(0, spring_constant))
			mesh.addPassiveVertex(v2)
			add_sucess = pts_list.add(PointMatch(v1, v2))
	 	pts_file.close()

	 	if len(pts_list) > MIN_NUM_MATCHES:
			tileA = tiles.get(secA)
			tileB = tiles.get(secB)
			init_meshes.addTile(tileA)
			init_meshes.addTile(tileB)
			tileB.connect(tileA, pts_list)	

# Use helper meshes to prealign
init_meshes.optimize(MAX_EPSILON * LAYER_SCALE,
					MAX_ITERATIONS,
					MAX_PLATEAU_WIDTH)

# Apply that prealign to meshes, then optimize it
for mesh, tile in zip(meshes, tiles):
	mesh.init(tile.getModel())
try:
	t0 = System.currentTimeMillis()
	Utils.log( "Optimizing spring meshes..." )
	SpringMesh.optimizeMeshes2(meshes,
								MAX_EPSILON * LAYER_SCALE,
								MAX_ITERATIONS,
								MAX_PLATEAU_WIDTH)
	Utils.log("Done optimizing spring meshes. Took " + 
					str(System.currentTimeMillis()-t0) + " ms")
except:
	Utils.log("Not enough data points to optimize!")

# Translate relative to bounding box
for mesh in meshes:
	for point_match in mesh.getVA().keySet():
		p1 = point_match.getP1()
		p2 = point_match.getP2()
		l = p1.getL()
		w = p2.getW()
		# Not sure these will act as pointers
		l[0] = l[0] / LAYER_SCALE + box.x
		l[1] = l[1] / LAYER_SCALE + box.y
		w[0] = w[0] / LAYER_SCALE + box.x
		w[1] = w[1] / LAYER_SCALE + box.y

# Free memory
project.getLoader().releaseAll()

# Collect current transforms from patches
inf_area = infinite_area()
vector_data = ArrayList()
for layer in layers:
	vector_data.addAll(
			cast_collection(layer.getDisplayables(VectorData, False, True),
			VectorData, True))
vector_data.addAll(
		cast_collection(layerset.getZDisplayables(VectorData, True),
		VectorData, True))

# Propagate before or propagate after
# TO DO

# Apply transforms to patches
progress = 0
for mesh, layer in zip(meshes, layers):
	Utils.log("Applying transforms to patches...")
	IJ.showProgress(0, len(layers))

	mlt = MovingLeastSquaresTransform2()
	mlt.setModel(AffineModel2D)
	mlt.setAlpha(2.0)
	mlt.setMatches(mesh.getVA().keySet())

	# ElasticLayerAlignment uses newer concurrent methods for this
	pool = Executors.newFixedThreadPool(MAX_NUM_THREADS)
	patch_transforms = []
	patches = layer.getDisplayables(Patch)
	for patch in patches:
		pt = PatchTransform(patch, mlt.copy())
		patch_transforms.append(pt)
	futures = pool.invokeAll(patch_transforms)
	for future in futures:
		print future.get(5, TimeUnit.SECONDS)
	shutdown_and_await_termination(pool, 5)

	for vd in vector_data:
		vd.apply(layer, inf_area, mlt)

	progress += 1
	IJ.showProgress(progress, len(layers))

for layer in layers:
	patches = layer.getDisplayables(Patch)
	for patch in patches:
		patch.updateMipMaps()


# if __name__ == '__main__':
# 	project = Project.getProject('turtle_rigid.xml')
# 	# directory = '~/seungmount/research/tommy/150502_piriform/affine_block_matching/'
# 	directory = '/usr/people/tmacrina/seungmount/research/tommy/trakem_tests/150703_elastic_redux/block_matching/'
# 	main(project, directory)