#!/usr/bin/python3
# -*- coding: utf-8 -*-
import os
import re
import json
import Title
import operator
import Config

global titles
titles = {}

def data():
	return titles

def items():
	return titles.items()

def get(key):
	return titles[key]
	
def contains(key):
	return key in titles
	
def set(key, value):
	titles[key] = value
	
#def titles():
#	return titles
	
def keys():
	return titles.keys()
	
def loadTitleFile(path, silent = False):
	with open(path, encoding="utf-8-sig") as f:
		loadTitleBuffer(f.read(), silent)
	
def loadTitleBuffer(buffer, silent = False):
	firstLine = True
	map = ['id', 'key', 'name']
	for line in buffer.split('\n'):
		line = line.strip()
		if len(line) == 0 or line[0] == '#':
			continue
		if firstLine:
			firstLine = False
			if re.match('[A-Za-z\|\s]+', line, re.I):
				map = line.split('|')
				continue
		
		t = Title.Title()
		t.loadCsv(line, map)

		if not t.id in keys():
			titles[t.id] = Title.Title()
			
		titleKey = titles[t.id].key
		titles[t.id].loadCsv(line, map)

		if not silent and titleKey != titles[t.id].key:
			print('Added new title key for ' + str(titles[t.id].name) + '[' + t.id + ']')

	
def load():
	if os.path.isfile("titles.txt"):
		loadTitleFile('titles.txt', True)

			
	files = [f for f in os.listdir(Config.paths.titleDatabase) if f.endswith('.txt')]
	files.sort()
	
	for file in files:
		loadTitleFile(Config.paths.titleDatabase + '/' + file, False)
	
def save(fileName = 'titles.txt', map = ['id', 'rightsId', 'key', 'isUpdate', 'isDLC', 'isDemo', 'name', 'version', 'region', 'retailOnly']):
	buffer = ''
	
	buffer += '|'.join(map) + '\n'
	for t in sorted(list(titles.values())):
		buffer += t.serialize(map) + '\n'
		
	with open(fileName, 'w', encoding='utf-8') as csv:
		csv.write(buffer)