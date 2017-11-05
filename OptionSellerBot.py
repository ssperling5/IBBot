#!/bin/python

import time
import csv

CONF_FILE = 'default.csv'

class OptionSeller:
	def __init__(self):
		self.conf_file = CONF_FILE
		self.stock_list_of_dicts = []
		self.parse_conf()
		print(self.stock_list_of_dicts)

	def parse_conf(self):
		# declare array to store data from csv
		data_array = []
		with open(self.conf_file, 'r') as csvfile:
			stock_reader = csv.reader(csvfile)
			i = 0
			for row in stock_reader:
				data_array.append(row)
				i += 1

		# the first row will be keys, and the next rows will be actual stock data
		# zip the data into a convenient list of dicts
		keys = data_array[0]
		for i in range (1, len(data_array)-1):
			self.stock_list_of_dicts.append(dict(zip(keys, data_array[i])))


def main():
	ops = OptionSeller()

if __name__ == '__main__':
	main()