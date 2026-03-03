#!/usr/bin/env python

# Author: _noblesse_oblige_ (Desura)

from __future__ import (
	absolute_import			 as _absolute_import,
	print_function			  as _print_function,
	division					as _division,
)

import sys

import argparse

import struct

import os
from os.path import (
	extsep					  as _path_extsep,
	curdir					  as _path_curdir,
	join						as _path_join,
	basename					as _path_basename,
	exists					  as _path_exists,
	isdir					   as _path_is_directory,
)

import mmap

from PIL import (
	Image,
)


def from_byte( image, offset ):
	return image[ offset ]


def from_string( image, offset, count = 0 ):
	""" Convert a sequence of NUL-terminated bytes to a Python string. """

	s_out = ""
	i = 0

	while True:
		c = image[ offset + i ]
		if 0 == c: break
		s_out += chr( c )
		i += 1
		if count and (i == count): break

	return s_out


def from_be_uint16( image, offset ):
	return struct.unpack_from( ">H", image, offset )[ 0 ]


def from_be_uint32( image, offset ):
	return struct.unpack_from( ">I", image, offset )[ 0 ]
	
def from_be_uint24( image, offset ):
	hi = struct.unpack_from( ">B", image, offset )[ 0 ] << 16
	lo = struct.unpack_from( ">H", image, offset+1 )[ 0 ]
	return hi + lo


def FalconTrueColor_pixel_to_RGB( pixel, fluff_lo_bits = False ):
	""" Extracts the red, green, and blue channels from 
		an Atari Falcon "True Color" pixel. """

	# RGB 5-6-5 format.
	# See `DecodeFalconTrueColor` at:
	#   http://sourceforge.net/p/fail/code/ci/master/tree/recoil.ci
	r = (pixel & 0xf800) >> 8
	g = (pixel & 0x07e0) >> 3
	b = (pixel & 0x001f) << 3
	# Note: Low order bits are fluffed from high order bits
	#	   to blend out the bit depth disparity between the color 
	#	   channels.
	if fluff_lo_bits:
		r |= (r >> 5)
		g |= (g >> 6)
		b |= (b >> 5)

	return r, g, b


class SpriteMetadata( object ):
	""" Metadata record for a TRS sprite. """


	_width	  = None
	_height	 = None
	_packed	 = None
	_offset	 = None
	_size	   = None
	_raw_bytes  = None


	@classmethod
	def from_bytearray( cls, image, offset, version):
		""" Create sprite metadata from given bytearray. """

		self = cls( )

		size = 0

		self._width			 = from_byte( image, offset + size )
		size += 1
		self._height			= from_byte( image, offset + size )
		size += 1
		size += 2   # Skip empty word.
		unpacked_data_offset	= from_be_uint32( image, offset + size )
		size += 4
		packed_data_offset	  = from_be_uint32( image, offset + size )
		size += 4
		self._packed			= bool( packed_data_offset )
		self._offset			= \
		packed_data_offset if self._packed else unpacked_data_offset

		if 0 == self._width:	self._width = 256
		if 0 == self._height:   self._height = 256

		self._size		  = size
		self._raw_bytes	 = image
		self._version = version

		return self


	@property
	def size( self ):
		""" Size of the metadata in bytes. """

		return self._size

	@property
	def pixels_count( self ):
		""" Number of pixels in the image data. """

		return self._width * self._height


	def print_indexed_summary( self, sprite_num = None, file = sys.stderr ):
		""" Prints a summary of the sprite metadata 
			with an optional index number. """

		print(
			"Sprite #{nbr}: {w} x {h}, "
			"having {packing} at {offset:08x}".format(
				nbr = sprite_num + 1,
				w = self._width, h = self._height,
				packing = \
					"packed data" if self._packed else "unpacked data",
				offset = self._offset
		) )


	def save_sprite_image_as(
		self,
		file_name, file_format,
		scan_line_length = 800, fluff_lo_bits = False,
		generate_alpha_channel = False
	):
		""" Loads the sprite image data into a new PIL image
			and then saves it into a file of the specified name. """

		if self._packed:
			video_memory = self._transcode_packed_pixels(
				scan_line_length = scan_line_length,
				fluff_lo_bits = fluff_lo_bits
			)
			if self._version < 4:
				raw_pixels = [ ]
				# TODO: Use Numpy for this.
				for row_number in range( self._height ):
					row_offset = row_number * scan_line_length
					raw_pixels.extend( video_memory[
						row_offset : row_offset + self._width
					] )
				#print( "\tTotal Number of Pixels: {0}".format(
				#	len( raw_pixels )
				#) )
			else:
				raw_pixels = video_memory
		else:
			raw_pixels = self._transcode_unpacked_pixels(
				fluff_lo_bits = fluff_lo_bits
			)

		# Add alpha channel, if desired.
		raw_RGBA_pixels = [ ]
		if generate_alpha_channel:
			for pixel in raw_pixels:
				if pixel:   pixel |= 0xff000000
				else:	   pixel |= 0x00ffffff
				raw_RGBA_pixels.append( pixel )
			raw_pixels = raw_RGBA_pixels

		# TODO: Convert magenta to a black shadow, if desired.

		# Construct and save the image proper.
		if generate_alpha_channel:
			im = Image.new(
				"RGBA", ( self._width, self._height), color = "black"
			)
		else:
			im = Image.new(
				"RGB", ( self._width, self._height), color = "black"
			)
		im.putdata( raw_pixels )
		im.save( file_name, file_format )


	def _transcode_unpacked_pixels( self, fluff_lo_bits = False ):
		""" Transcodes an array of unpacked pixels into RGB pixels. """

		offset = self._offset

		# TODO? Use Numpy fanciness here instead.
		raw_pixels = [ ]
		for pixel_number in range( self.pixels_count ):

			pixel = from_be_uint16( self._raw_bytes, offset )
			offset += 2
			r, g, b = FalconTrueColor_pixel_to_RGB( pixel, fluff_lo_bits )
			# Store as 24-bit RGB pixel.
			raw_pixels.append( b << 16 | g << 8 | r )

		return raw_pixels


	def _transcode_packed_pixels(
		self,
		scan_line_length = 800, fluff_lo_bits = False
	):
		""" Transcodes an array of packed pixel chunks into RGB pixels. """
		raw_bytes = self._raw_bytes
		raw_pixels = [ ]
		offset = self._offset
		if self._version < 4:
			# Note: Need one more chunk than specified to get offsets to add up to 
			#	   start of next sprite.
			chunks_count = from_be_uint16( raw_bytes, offset ) + 1
			offset += 2
			#print( "\tNumber of Chunks: {0}".format( chunks_count ) )

			pixels_recorded = 0
			

			for chunk_number in range( chunks_count ):

				#print( "\tChunk Number: {0}".format( chunk_number ) )

				# Note: Screen offset is in bytes. So, convert to pixel count.
				screen_offset = from_be_uint16( raw_bytes, offset ) // 2
				offset += 2
				#print( "\t\tNumber of Blank Pixels: {0}".format( screen_offset ) )

				# Adjust screen pointer offset as appropriate.
				if scan_line_length < screen_offset:
					screen_offset += pixels_recorded
					pixels_recorded = 0
				else:
					pixels_recorded += screen_offset

				# Record run of blank pixels.
				raw_pixels.extend( [ 0 ] * screen_offset )

				pixels_count = from_be_uint16( raw_bytes, offset )
				offset += 2
				# Spec says number of data words - 1.
				# So, if 0 data words, then paint no additional pixels.
				if 0x8000 & pixels_count: continue
				pixels_count += 1
				#print( "\t\tNumber of Color Pixels: {0}".format( pixels_count ) )

				# Record color pixels.
				for pixel_number in range( pixels_count ):
					pixel = from_be_uint16( self._raw_bytes, offset )
					offset += 2
					r, g, b = FalconTrueColor_pixel_to_RGB( pixel, fluff_lo_bits )
					# Store as 24-bit RGB pixel.
					raw_pixels.append( b << 16 | g << 8 | r )
				pixels_recorded += pixels_count

			# Pad remainder of image with blank pixels, if necessary.
			pixels_count = scan_line_length * self._height
			if pixels_count > len( raw_pixels ):
				raw_pixels.extend( [ 0 ] * (pixels_count - len( raw_pixels )) )

			print( "\tFinal Offset: {0:08x}".format( offset ) )

			return raw_pixels
		# v4 type compression looks to be different
		# this is simply blindly copying the implementation that appears in the executable 
		# in the hope that it works correctly, hence the lack of useful variable names
		hasalpha = from_be_uint16(raw_bytes, offset)
		offset += 2
		chunks_count = from_be_uint16( raw_bytes, offset ) + 1
		offset += 2
		postowriteto = 0
		raw_pixels = [0]*(self._height * self._width)
		print(f"Hasalpha: {hasalpha}")
		print(f"Chunk count: {chunks_count	}")
		try:
			for chunk_number in range(0, chunks_count):
				unk2 = from_byte(raw_bytes, offset)
				if unk2 == 0xff:
					unk3 = from_be_uint24(raw_bytes, offset+1)
					offset += 4
				else:
					unk3 = unk2
					offset += 1
					#print(f"Read write offset {unk3}, offset now {hex(offset)}")
				postowriteto += unk3
				unk2 = from_byte(raw_bytes, offset)
				if unk2 == 0xff:
					unk4 = from_be_uint24(raw_bytes, offset+1)
					offset += 4
				else:
					unk4 = unk2
					offset += 1
					#print(f"Read pixelcount {unk4}, offset now {hex(offset)}")
				#print(f"Chunk {chunk_number} contains {unk4} pixels, write at {postowriteto}...")
				if unk4 > 0:
					while 1:
						unk5 = from_be_uint16(raw_bytes, offset)
						offset += 2
						#print(f"Read the two bytes of image data {unk5}, offset now {hex(offset)}")
						alpha = 0xff
						if hasalpha == 1:
							alpha = from_byte(raw_bytes, offset)
							offset += 1
						if postowriteto < self._width * self._height:
							unk8 = unk5 >> 3
							unk9 = (unk5 >> 8) & 0xf8
							r = unk9
							b = (unk5 & 0x1f) * 8
							# pink shadow to alpha conversion
							if hasalpha != 1:
								if unk5 & 0xf800 == 0:
									if unk8 & 0xfc == 0 and unk5 & 0x1f == 0:
										alpha = 0
								else:
									if (0xf5 < unk9) and (unk8 & 0xfc == 0) and (0xf5 < b):
										r = 0
										alpha = 0x80
										b = 0
							g = unk8 & 0xfc
							raw_pixels[postowriteto] =  b << 16 | g << 8 | r
							#print(f"Write pixel {r} {g} {b} {alpha} to loc {postowriteto}")
							postowriteto += 1
						unk4 -= 1
						if unk4 <= 0:
							break
		except:
			print(f"Error: Failed to unpack at offset {offset}")
		#print(raw_pixels)
		print( "\tFinal Offset: {0:08x}".format( offset ) )
		return raw_pixels

if "__main__" == __name__:
	
	rc = 0

	clargs_parser = argparse.ArgumentParser(
		description = "Dump sprites from TRS files created by Spooky Sprites."
	)
	clargs_parser.add_argument(
		"-o", "--output-directory-path", metavar = "DIRECTORY", type = str,
		default = _path_curdir,
	)
	clargs_parser.add_argument(
		"-F", "--output-format", metavar = "FORMAT", type = str,
		default = "TGA",
	)
	clargs_parser.add_argument(
		"-L", "--fluff-lo-bits", action = "store_true", default = False,
	)
	clargs_parser.add_argument(
		"-A", "--generate-alpha-channel", action = "store_true",
		default = False,
	)
	clargs_parser.add_argument(
		"trs_file_paths", metavar = "FILE", type = str, nargs = "+",
	)

	clargs = clargs_parser.parse_args( )

	directory_path = clargs.output_directory_path
	if not _path_exists( directory_path ):
		os.mkdir( directory_path, 0o700 )
	else:
		if not _path_is_directory( directory_path ):
			raise IOError( "Not a directory: {0}".format(
				directory_path
			) )
		if not os.access( directory_path, os.R_OK | os.W_OK | os.X_OK ):
			raise IOError( "Could not access directory: {0}".format(
				directory_path
			) )

	output_format = clargs.output_format
	
	print(clargs.trs_file_paths)
	if len(clargs.trs_file_paths) == 1 and os.path.isdir(clargs.trs_file_paths[0]):
		l = []
		for file in os.listdir(clargs.trs_file_paths[0]):
			if file.lower().endswith(".trs"):
				l.append(os.path.join(clargs.trs_file_paths[0], file))
		clargs.trs_file_paths = l

	for file_path in clargs.trs_file_paths:
		print(f"Processing file {file_path}")
		#if not file_path.endswith("flag.trs"): continue
		# TODO: Notify user which file is being processed.

		if not os.access( file_path, os.R_OK ):
			raise IOError( "Could not find or read the file: {0}".format(
				file_path
			) )

		basename = _path_basename( file_path ).split( _path_extsep )[ 0 ]

		with open( file_path, "rb" ) as binary_file:
			with mmap.mmap(
				binary_file.fileno( ), 0, access = mmap.ACCESS_READ
			) as image:

				offset = 0

				format_identifier = from_string( image, offset, 4 )
				if "TCSF" != format_identifier:
					raise IOError( "Not a valid TRS file: {0}".format(
						file_path
					) )
				offset += 4

				sprites_count = from_be_uint16( image, offset )
				offset += 2
				file_version = from_be_uint16( image, offset )
				if file_version not in [ 2, 3, 4 ]:
					print("Incompatible version for TRS file: v{0} {1}".format(
							file_version, file_path))
					continue
					raise IOError(
						"Incompatible version for TRS file: v{0} {1}".format(
							file_version, file_path
						)
					)
				offset += 2
				scan_line_length = from_be_uint16( image, offset )
				offset += 2
				offset += 2	 # Skip empty word.

				print( "File Format Version: {0}".format( file_version ) )
				print( "Number of Sprites: {0}".format( sprites_count ) )
				print( "Scan Line Length: {0}".format( scan_line_length ) )

				for sprite_num in range( sprites_count ):
					
					sprite_metadata = SpriteMetadata.from_bytearray(
						image, offset, file_version
					)
					offset += sprite_metadata.size
					#print(f"Processing {sprite_num} at offset {offset}")

					sprite_metadata.print_indexed_summary( sprite_num )
					path_base = _path_join( directory_path, basename )
					if not os.path.isdir(f"{path_base}"):
						os.mkdir(f"{path_base}")
					sprite_metadata.save_sprite_image_as(
						"{path_base}/{nbr:04d}{sep}{ext}".format(
							path_base = path_base, nbr = sprite_num,
							sep = _path_extsep, ext = output_format.lower( ),
						),
						output_format.upper( ),
						scan_line_length = scan_line_length,
						fluff_lo_bits = clargs.fluff_lo_bits,
						generate_alpha_channel = 
						clargs.generate_alpha_channel,
					)

	raise SystemExit( rc )


# vim: set ft=python ts=4 sts=4 sw=4 et tw=79: