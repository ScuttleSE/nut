#!/usr/bin/python3
# -*- coding: utf-8 -*-

import argparse
import base64
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import xml.dom.minidom as minidom
import xml.etree.ElementTree as ET
from binascii import hexlify as hx, unhexlify as uhx
from hashlib import sha256
from struct import pack as pk, unpack as upk
from io import TextIOWrapper
from tqdm import tqdm
import Titles
import requests
import unidecode
import urllib3

#Global Vars
titlekey_list = []
quiet = False
truncateName = False
enxhop = False

def print_(*info):
	if not quiet:
		print(' '.join(map(str,info)))

def read_at(f, off, len):
	f.seek(off)
	return f.read(len)

def read_u8(f, off):
	return upk('<B', read_at(f, off, 1))[0]


def read_u16(f, off):
	return upk('<H', read_at(f, off, 2))[0]


def read_u32(f, off):
	return upk('<I', read_at(f, off, 4))[0]


def read_u48(f, off):
	s = upk('<HI', read_at(f, off, 6))
	return 0x10000 * s[1] + s[0]


def read_u64(f, off):
	return upk('<Q', read_at(f, off, 8))[0]

def calc_sha256(fPath):
	f = open(fPath, 'rb')
	fSize = os.path.getsize(fPath)
	hash = sha256()
	
	if fSize >= 10000:
		t = tqdm(total=fSize, unit='B', unit_scale=True, desc=os.path.basename(fPath), leave=False)
		while True:
			buf = f.read(4096)
			if not buf:
				break
			hash.update(buf)
			t.update(len(buf))
		t.close()
	else:
		hash.update(f.read())
	f.close()
	return hash.hexdigest()


def load_config(fPath):
	dir = os.path.dirname(__file__)

	config = {'Paths': {
		'hactoolPath': 'hactool',
		'keysPath': 'keys.txt',
		'NXclientPath': 'nx_tls_client_cert.pem',
		'ShopNPath': 'ShopN.pem'},
		'Values': {
			'Region': 'US',
			'Firmware': '5.1.0-0',
			'DeviceID': '0000000000000000',
			'Environment': 'lp1',
			'TitleKeysURL': '',
			'NspOut': '_NSPOUT'}}
	try:
		f = open(fPath, 'r')
	except FileNotFoundError:
		f = open(fPath, 'w')
		json.dump(config, f)
		f.close()
		f = open(fPath, 'r')

	j = json.load(f)

	hactoolPath = j['Paths']['hactoolPath']
	keysPath = j['Paths']['keysPath']
	NXclientPath = j['Paths']['NXclientPath']
	ShopNPath = j['Paths']['ShopNPath']

	reg = j['Values']['Region']
	fw = j['Values']['Firmware']
	deviceId = j['Values']['DeviceID']
	env = j['Values']['Environment']
	dbURL = j['Values']['TitleKeysURL']
	nspout = j['Values']['NspOut']

	if platform.system() == 'Linux':
		hactoolPath = './' + hactoolPath + '_linux'

	if platform.system() == 'Darwin':
		hactoolPath = './' + hactoolPath + '_mac'

	return hactoolPath, keysPath, NXclientPath, ShopNPath, reg, fw, deviceId, env, dbURL, nspout


def make_request(method, url, certificate='', hdArgs={}):
	if certificate == '':  # Workaround for defining errors
		certificate = NXclientPath

	reqHd = {'User-Agent': 'NintendoSDK Firmware/%s (platform:NX; eid:%s)' % (fw, env),
			 'Accept-Encoding': 'gzip, deflate',
			 'Accept': '*/*',
			 'Connection': 'keep-alive'}
	reqHd.update(hdArgs)

	r = requests.request(method, url, cert=certificate, headers=reqHd, verify=False, stream=True)

	if r.status_code == 403:
		print_('Request rejected by server! Check your cert.')
		return r

	return r


def get_versions(titleId):
	# url = 'https://tagaya.hac.%s.eshop.nintendo.net/tagaya/hac_versionlist' % env
	url = 'https://superfly.hac.%s.d4c.nintendo.net/v1/t/%s/dv' % (env, titleId)
	r = make_request('GET', url)
	j = r.json()

	try:
		if j['error']:
			return ['none']
	except Exception as e:
		pass
	try:
		lastestVer = j['version']
		if lastestVer < 65536:
			return ['%s' % lastestVer]
		else:
			versionList = ('%s' % "-".join(str(i) for i in range(0x10000, lastestVer + 1, 0x10000))).split('-')
			if titleId.endswith("00"):
				return versionList
			return [versionList[0]]
	except Exception as e:
		return ['none']
		
def get_version(titleId):
	# url = 'https://tagaya.hac.%s.eshop.nintendo.net/tagaya/hac_versionlist' % env
	url = 'https://superfly.hac.%s.d4c.nintendo.net/v1/t/%s/dv' % (env, titleId)
	r = make_request('GET', url)
	j = r.json()
	#print('v: ' + str(j))
	try:
		if j['error']:
			return None
	except Exception as e:
		pass
	try:
		return str(j['version'])
	except Exception as e:
		return None
		
def get_versionUpdates():
	url = 'https://tagaya.hac.%s.eshop.nintendo.net/tagaya/hac_versionlist' % env
	r = make_request('GET', url)
	j = r.json()
	r = {}
	try:
		if j['error']:
			return r
	except Exception as e:
		pass
		
	for i in j['titles']:
		try:
			r[i['id']] = i['version']
		except Exception as e:
			pass
	return r

def get_name(titleId):
	titleId = titleId.upper()
	lines = titlekey_list
	if Titles.contains(titleId):
			try:
				t = Titles.get(titleId)
				return re.sub(r'[/\\:*?!"|™©®]+', "", unidecode.unidecode(t.name.strip()))
			except:
				pass
	return 'Unknown Title'


def download_file(url, fPath):
	fName = os.path.basename(fPath).split()[0]

	if os.path.exists(fPath):
		dlded = os.path.getsize(fPath)
		r = make_request('GET', url, hdArgs={'Range': 'bytes=%s-' % dlded})

		if r.headers.get('Server') != 'openresty/1.9.7.4':
			print_('\nDownload is already complete, skipping!')
			return fPath
		elif r.headers.get('Content-Range') == None:  # CDN doesn't return a range if request >= filesize
			fSize = int(r.headers.get('Content-Length'))
		else:
			fSize = dlded + int(r.headers.get('Content-Length'))

		if dlded == fSize:
			print_('\nDownload is already complete, skipping!')
			return fPath
		elif dlded < fSize:
			print_('\nResuming download...')
			f = open(fPath, 'ab')
		else:
			print_('\nExisting file is bigger than expected (%s/%s), restarting download...' % (dlded, fSize))
			dlded = 0
			f = open(fPath, "wb")
	else:
		dlded = 0
		r = make_request('GET', url)
		fSize = int(r.headers.get('Content-Length'))
		f = open(fPath, 'wb')

	chunkSize = 1000
	if tqdmProgBar == True and fSize >= 10000:
		for chunk in tqdm(r.iter_content(chunk_size=chunkSize), initial=dlded // chunkSize, total=fSize // chunkSize,
						  desc=fName, unit='kb', smoothing=1, leave=False):
			f.write(chunk)
			dlded += len(chunk)
	elif fSize >= 10000:
		for chunk in r.iter_content(
				chunkSize):  # https://stackoverflow.com/questions/15644964/python-progress-bar-and-downloads
			f.write(chunk)
			dlded += len(chunk)
			done = int(50 * dlded / fSize)
			sys.stdout.write('\r%s:  [%s%s] %d/%d b' % (fName, '=' * done, ' ' * (50 - done), dlded, fSize))
			sys.stdout.flush()
		sys.stdout.write('\033[F')
	else:
		f.write(r.content)
		dlded += len(r.content)

	if fSize != 0 and dlded != fSize:
		raise ValueError('Downloaded data is not as big as expected (%s/%s)!' % (dlded, fSize))

	f.close()
	print_('\r\nSaved to %s!' % f.name)
	return fPath


def decrypt_NCA(fPath, outDir=''):
	fName = os.path.basename(fPath).split()[0]

	if outDir == '':
		outDir = os.path.splitext(fPath)[0]
	os.makedirs(outDir, exist_ok=True)

	commandLine = hactoolPath + ' "' + fPath + '"' + keysArg \
				  + ' --exefsdir="' + outDir + os.sep + 'exefs"' \
				  + ' --romfsdir="' + outDir + os.sep + 'romfs"' \
				  + ' --section0dir="' + outDir + os.sep + 'section0"' \
				  + ' --section1dir="' + outDir + os.sep + 'section1"' \
				  + ' --section2dir="' + outDir + os.sep + 'section2"' \
				  + ' --section3dir="' + outDir + os.sep + 'section3"' \
				  + ' --header="' + outDir + os.sep + 'Header.bin"'

	try:
		print(commandLine)
		subprocess.check_output(commandLine, shell=True)
		if os.listdir(outDir) == []:
			raise subprocess.CalledProcessError('\nDecryption failed, output folder %s is empty!' % outDir)
	except subprocess.CalledProcessError:
		print_('\nDecryption failed!')
		raise

	return outDir


def verify_NCA(ncaFile, titleKey):
	if not titleKey:
		return False
	
	commandLine = hactoolPath + ' "' + ncaFile + '"' + keysArg + ' --titlekey="' + titleKey + '"'

	try:
		output = str(subprocess.check_output(commandLine, stderr=subprocess.STDOUT, shell=True))
	except subprocess.CalledProcessError as exc:
		print_("Status : FAIL", exc.returncode, exc.output)
		return False
	else:
		if "Error: section 0 is corrupted!" in output or "Error: section 1 is corrupted!" in output:
			print_("\nNCA Verification failed. Probably a bad titlekey.")
			return False
	print_("\nTitlekey verification successful.")
	return True


def get_biggest_file(path):
	try:
		objects = os.listdir(path)
		sofar = 0
		name = ""
		for item in objects:
			size = os.path.getsize(os.path.join(path, item))
			if size > sofar:
				sofar = size
				name = item
		return os.path.join(path, name)
	except Exception as e:
		print_(e)


def download_cetk(rightsID, fPath):
	url = 'https://atum.hac.%s.d4c.nintendo.net/r/t/%s?device_id=%s' % (env, rightsID, deviceId)
	r = make_request('HEAD', url)
	id = r.headers.get('X-Nintendo-Content-ID')

	url = 'https://atum.hac.%s.d4c.nintendo.net/c/t/%s?device_id=%s' % (env, id, deviceId)
	cetk = download_file(url, fPath)

	return cetk


def download_title(gameDir, titleId, ver, tkey=None, nspRepack=False, n='', verify=False):
	print_('\n%s v%s:' % (titleId, ver))
	titleId = titleId.lower()
	isNsx = False
	
	if tkey:
		tkey = tkey.lower()
		
	if len(titleId) != 16:
		titleId = (16 - len(titleId)) * '0' + titleId

	url = 'https://atum%s.hac.%s.d4c.nintendo.net/t/a/%s/%s?device_id=%s' % (n, env, titleId, ver, deviceId)
	print_(url)
	try:
		r = make_request('HEAD', url)
	except Exception as e:
		print_("Error downloading title. Check for incorrect titleid or version.")
		return
	CNMTid = r.headers.get('X-Nintendo-Content-ID')

	if CNMTid == None:
		print_('title not available on CDN')
		return

	print_('\nDownloading CNMT (%s.cnmt.nca)...' % CNMTid)
	url = 'https://atum%s.hac.%s.d4c.nintendo.net/c/a/%s?device_id=%s' % (n, env, CNMTid, deviceId)
	fPath = os.path.join(gameDir, CNMTid + '.cnmt.nca')
	cnmtNCA = download_file(url, fPath)
	cnmtDir = decrypt_NCA(cnmtNCA)
	CNMT = cnmt(os.path.join(cnmtDir, 'section0', os.listdir(os.path.join(cnmtDir, 'section0'))[0]),
				os.path.join(cnmtDir, 'Header.bin'))

	if nspRepack == True:
		outf = os.path.join(gameDir, '%s.xml' % os.path.basename(cnmtNCA.strip('.nca')))
		cnmtXML = CNMT.gen_xml(cnmtNCA, outf)

		rightsID = '%s%s%s' % (titleId, (16 - len(CNMT.mkeyrev)) * '0', CNMT.mkeyrev)

		tikPath = os.path.join(gameDir, '%s.tik' % rightsID)
		certPath = os.path.join(gameDir, '%s.cert' % rightsID)
		if CNMT.type == 'Application' or CNMT.type == 'AddOnContent':
			shutil.copy(os.path.join(os.path.dirname(__file__), 'Certificate.cert'), certPath)

			if tkey:
				with open(os.path.join(os.path.dirname(__file__), 'Ticket.tik'), 'rb') as intik:
					data = bytearray(intik.read())
					data[0x180:0x190] = uhx(tkey)
					data[0x286] = int(CNMT.mkeyrev)
					data[0x2A0:0x2B0] = uhx(rightsID)

					with open(tikPath, 'wb') as outtik:
						outtik.write(data)
			else:
				isNsx = True
				with open(os.path.join(os.path.dirname(__file__), 'Ticket.tik'), 'rb') as intik:
					data = bytearray(intik.read())
					data[0x180:0x190] = uhx('00000000000000000000000000000000')
					data[0x286] = int(CNMT.mkeyrev)
					data[0x2A0:0x2B0] = uhx(rightsID)

					with open(tikPath, 'wb') as outtik:
						outtik.write(data)

			print_('\nGenerated %s and %s!' % (os.path.basename(certPath), os.path.basename(tikPath)))
		elif CNMT.type == 'Patch':
			print_('\nDownloading cetk...')

			with open(download_cetk(rightsID, os.path.join(gameDir, '%s.cetk' % rightsID)), 'rb') as cetk:
				cetk.seek(0x180)
				tkey = hx(cetk.read(0x10)).decode()
				print_('\nTitlekey: %s' % tkey)

				with open(tikPath, 'wb') as tik:
					cetk.seek(0x0)
					tik.write(cetk.read(0x2C0))

				with open(certPath, 'wb') as cert:
					cetk.seek(0x2C0)
					cert.write(cetk.read(0x700))

			print_('\nExtracted %s and %s from cetk!' % (os.path.basename(certPath), os.path.basename(tikPath)))

	NCAs = {
		0: [],
		1: [],
		2: [],
		3: [],
		4: [],
		5: [],
		6: [],
	}
	for type in [0, 3, 4, 5, 1, 2, 6]:  # Download smaller files first
		for ncaID in CNMT.parse(CNMT.ncaTypes[type]):
			print_('\nDownloading %s entry (%s.nca)...' % (CNMT.ncaTypes[type], ncaID))
			url = 'https://atum%s.hac.%s.d4c.nintendo.net/c/c/%s?device_id=%s' % (n, env, ncaID, deviceId)
			fPath = os.path.join(gameDir, ncaID + '.nca')
			NCAs[type].append(download_file(url, fPath))
			if verify:
				if calc_sha256(fPath) != CNMT.parse(CNMT.ncaTypes[type])[ncaID][2]:
					print_('\n\n%s is corrupted, hashes don\'t match!' % os.path.basename(fPath))
				else:
					print_('\nVerified %s...' % os.path.basename(fPath))

	if nspRepack == True:
		files = []
		files.append(certPath)
		files.append(tikPath)
		for key in [1, 5, 2, 4, 6]:
			files.extend(NCAs[key])
		files.append(cnmtNCA)
		files.append(cnmtXML)
		files.extend(NCAs[3])
		return files


def download_game(titleId, ver, tkey=None, nspRepack=False, name='', verify=False):
	name = get_name(titleId)
	gameType = ''

	if name == 'Uknown Title':
		temp = "[" + titleId + "]"
	else:
		temp = name + " [" + titleId + "]"

	basetitleId = ''
	if titleId.endswith('000'):  # Base game
		gameDir = os.path.join(os.path.dirname(__file__), temp)
		gameType = 'BASE'
	elif titleId.endswith('800'):  # Update
		basetitleId = '%s000' % titleId[:-3]
		gameDir = os.path.join(os.path.dirname(__file__), temp)
		gameType = 'UPD'
	else:  # DLC
		basetitleId = '%s%s000' % (titleId[:-4], str(int(titleId[-4], 16) - 1))
		gameDir = os.path.join(os.path.dirname(__file__), temp)
		gameType = 'DLC'

	os.makedirs(gameDir, exist_ok=True)

	outputDir = os.path.join(os.path.dirname(__file__), nspout)

	if not os.path.exists(outputDir):
		os.makedirs(outputDir, exist_ok=True)

   
	if name != "":
		if gameType == 'BASE':
			 outf = os.path.join(outputDir, '%s [%s][v%s]' % (name,titleId,ver))
		else:
			outf = os.path.join(outputDir, '%s [%s][%s][v%s]' % (name,gameType,titleId,ver))
	else:
		if gameType == 'BASE':
			outf = os.path.join(outputDir, '%s [v%s]' % (titleId,ver))
		else:
			outf = os.path.join(outputDir, '%s [%s][v%s]' % (titleId,gameType,ver))

	if truncateName:
		name = name.replace(' ','')[0:20]
		outf = os.path.join(outputDir, '%s%sv%s' % (name,titleId,ver))


	if tkey:
		outf = outf + '.nsp'
	else:
		outf = outf + '.nsx'

	for item in os.listdir(outputDir):
		if item.find('%s' % titleId) != -1:
			if item.find('v%s' % ver) != -1:
				print_('%s already exists, skipping download' % outf)
				shutil.rmtree(gameDir)
				return


	files = download_title(gameDir, titleId, ver, tkey, nspRepack, verify=verify)

	if gameType != 'UPD':
		if tkey:
			verified = verify_NCA(get_biggest_file(gameDir), tkey)

			if not verified:
				shutil.rmtree(gameDir)
				print_('\ncleaned up downloaded content')
				return

	if nspRepack == True:
		if files == None:
			return
		NSP = nsp(outf, files)
		print_('\nstarting repack, This may take a while')
		NSP.repack()
		shutil.rmtree(gameDir)
		print_('\ncleaned up downloaded content')

		if enxhop:
			enxhopDir = os.path.join(outputDir,'switch')
			os.makedirs(enxhopDir, exist_ok=True)
			with open(os.path.join(enxhopDir,'eNXhop.txt'), 'a+') as f:
				f.write(titleId + '\n')

		return outf

	return gameDir


class cnmt:
	def __init__(self, fPath, hdPath):
		self.packTypes = {0x1: 'SystemProgram',
						  0x2: 'SystemData',
						  0x3: 'SystemUpdate',
						  0x4: 'BootImagePackage',
						  0x5: 'BootImagePackageSafe',
						  0x80: 'Application',
						  0x81: 'Patch',
						  0x82: 'AddOnContent',
						  0x83: 'Delta'}

		self.ncaTypes = {0: 'Meta', 1: 'Program', 2: 'Data', 3: 'Control',
						 4: 'HtmlDocument', 5: 'LegalInformation', 6: 'DeltaFragment'}

		f = open(fPath, 'rb')

		self.path = fPath
		self.type = self.packTypes[read_u8(f, 0xC)]
		self.id = '0%s' % format(read_u64(f, 0x0), 'x')
		self.ver = str(read_u32(f, 0x8))
		self.sysver = str(read_u64(f, 0x28))
		self.dlsysver = str(read_u64(f, 0x18))
		self.digest = hx(read_at(f, f.seek(0, 2) - 0x20, f.seek(0, 2))).decode()

		with open(hdPath, 'rb') as ncaHd:
			self.mkeyrev = str(read_u8(ncaHd, 0x220))

		f.close()

	def parse(self, ncaType=''):
		f = open(self.path, 'rb')

		data = {}
		if self.type == 'SystemUpdate':
			EntriesNB = read_u16(f, 0x12)
			for n in range(0x20, 0x10 * EntriesNB, 0x10):
				titleId = hex(read_u64(f, n))[2:]
				if len(titleId) != 16:
					titleId = '%s%s' % ((16 - len(titleId)) * '0', titleId)
				ver = str(read_u32(f, n + 0x8))
				packType = self.packTypes[read_u8(f, n + 0xC)]

				data[titleId] = ver, packType
		else:
			tableOffset = read_u16(f, 0xE)
			contentEntriesNB = read_u16(f, 0x10)
			cmetadata = {}
			for n in range(contentEntriesNB):
				offset = 0x20 + tableOffset + 0x38 * n
				hash = hx(read_at(f, offset, 0x20)).decode()
				titleId = hx(read_at(f, offset + 0x20, 0x10)).decode()
				size = str(read_u48(f, offset + 0x30))
				type = self.ncaTypes[read_u16(f, offset + 0x36)]

				if type == ncaType or ncaType == '':
					data[titleId] = type, size, hash

		f.close()
		return data

	def gen_xml(self, ncaPath, outf):
		data = self.parse()
		hdPath = os.path.join(os.path.dirname(ncaPath),
							  '%s.cnmt' % os.path.basename(ncaPath).split('.')[0], 'Header.bin')
		with open(hdPath, 'rb') as ncaHd:
			mKeyRev = str(read_u8(ncaHd, 0x220))

		ContentMeta = ET.Element('ContentMeta')

		ET.SubElement(ContentMeta, 'Type').text = self.type
		ET.SubElement(ContentMeta, 'Id').text = '0x%s' % self.id
		ET.SubElement(ContentMeta, 'Version').text = self.ver
		ET.SubElement(ContentMeta, 'RequiredDownloadSystemVersion').text = self.dlsysver

		n = 1
		for titleId in data:
			locals()["Content" + str(n)] = ET.SubElement(ContentMeta, 'Content')
			ET.SubElement(locals()["Content" + str(n)], 'Type').text = data[titleId][0]
			ET.SubElement(locals()["Content" + str(n)], 'Id').text = titleId
			ET.SubElement(locals()["Content" + str(n)], 'Size').text = data[titleId][1]
			ET.SubElement(locals()["Content" + str(n)], 'Hash').text = data[titleId][2]
			ET.SubElement(locals()["Content" + str(n)], 'KeyGeneration').text = mKeyRev
			n += 1

		# cnmt.nca itself
		cnmt = ET.SubElement(ContentMeta, 'Content')
		ET.SubElement(cnmt, 'Type').text = 'Meta'
		ET.SubElement(cnmt, 'Id').text = os.path.basename(ncaPath).split('.')[0]
		ET.SubElement(cnmt, 'Size').text = str(os.path.getsize(ncaPath))
		hash = sha256()
		with open(ncaPath, 'rb') as nca:
			hash.update(nca.read())  # Buffer not needed
		ET.SubElement(cnmt, 'Hash').text = hash.hexdigest()
		ET.SubElement(cnmt, 'KeyGeneration').text = mKeyRev

		ET.SubElement(ContentMeta, 'Digest').text = self.digest
		ET.SubElement(ContentMeta, 'KeyGenerationMin').text = self.mkeyrev
		ET.SubElement(ContentMeta, 'RequiredSystemVersion').text = self.sysver
		if self.id.endswith('800'):
			ET.SubElement(ContentMeta, 'PatchId').text = '0x%s000' % self.id[:-3]
		else:
			ET.SubElement(ContentMeta, 'PatchId').text = '0x%s800' % self.id[:-3]

		string = ET.tostring(ContentMeta, encoding='utf-8')
		reparsed = minidom.parseString(string)
		with open(outf, 'w') as f:
			f.write(reparsed.toprettyxml(encoding='utf-8', indent='  ').decode()[:-1])

		print_('\nGenerated %s!' % os.path.basename(outf))
		return outf

class nsp:
	def __init__(self, outf, files):
		self.path = outf
		self.files = files

	def repack(self):
		print_('\tRepacking to NSP...')
		
		hd = self.gen_header()
		
		totSize = len(hd) + sum(os.path.getsize(file) for file in self.files)
		if os.path.exists(self.path) and os.path.getsize(self.path) == totSize:
			print_('\t\tRepack %s is already complete!' % self.path)
			return
			
		t = tqdm(total=totSize, unit='B', unit_scale=True, desc=os.path.basename(self.path), leave=False)
		
		t.write('\t\tWriting header...')
		outf = open(self.path, 'wb')
		outf.write(hd)
		t.update(len(hd))
		
		done = 0
		for file in self.files:
			t.write('\t\tAppending %s...' % os.path.basename(file))
			with open(file, 'rb') as inf:
				while True:
					buf = inf.read(4096)
					if not buf:
						break
					outf.write(buf)
					t.update(len(buf))
		t.close()
		
		print_('\t\tRepacked to %s!' % outf.name)
		outf.close()

	def gen_header(self):
		filesNb = len(self.files)
		stringTable = '\x00'.join(os.path.basename(file) for file in self.files)
		headerSize = 0x10 + (filesNb)*0x18 + len(stringTable)
		remainder = 0x10 - headerSize%0x10
		headerSize += remainder
		
		fileSizes = [os.path.getsize(file) for file in self.files]
		fileOffsets = [sum(fileSizes[:n]) for n in range(filesNb)]
		
		fileNamesLengths = [len(os.path.basename(file))+1 for file in self.files] # +1 for the \x00
		stringTableOffsets = [sum(fileNamesLengths[:n]) for n in range(filesNb)]
		
		header =  b''
		header += b'PFS0'
		header += pk('<I', filesNb)
		header += pk('<I', len(stringTable)+remainder)
		header += b'\x00\x00\x00\x00'
		for n in range(filesNb):
			header += pk('<Q', fileOffsets[n])
			header += pk('<Q', fileSizes[n])
			header += pk('<I', stringTableOffsets[n])
			header += b'\x00\x00\x00\x00'
		header += stringTable.encode()
		header += remainder * b'\x00'
		
		return header




