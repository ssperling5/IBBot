#!/bin/python

# used for sleep
import time
# date operations
import datetime
# used for exiting program upon error
import sys
# library for interacing with csv files
import csv
# python logging library for monitoring and debugging
import logging
# interface class to IB market data
from ibInterface import IbInterface
from threading import Thread

# for catching sigint
import signal

# CSV file for stock data and appropriate parameters
STOCK_CSV = 'default.csv'
# Conf file for global configuration parameters of the OptionSeller
GLOBAL_CONF = 'global.conf'

# Set logging level
logging.basicConfig(format='%(levelname)s:%(message)s', level=logging.DEBUG)

# Class for selling put and call options on desired stocks at desired target prices
class OptionSeller:
	def __init__(self):
		# Parse global parameters

		# extract data from stock csv file into a list of dicts for easy use
		self.stock_csv = STOCK_CSV
		self.stock_list_of_dicts = []
		self.parse_stocks()

		# Buy and sell thresholds for options selling
		self.buy_thresh = .02
		self.sell_thresh = .01

		# Amount of loops to wait before modifying order, and amount of modifications before giving up
		self.loop_max = 2
		self.mod_max = 2

		# Interface to IB api
		self.ibif = IbInterface()

		logging.debug('Imported the following stock data: ')
		for row in self.stock_list_of_dicts:
			logging.debug(row)

		self.quote_list = []
		self.position_list = []
		self.call_order_list = []
		self.put_order_list = []
		self.trade_thread = Thread(target=self.trade_loop)
		self.trade = True
		self.trade_thread.start()

	# extract data from the stock csv file
	def parse_stocks(self):
		# declare array to store data from csv
		logging.debug("Parsing stock csv")
		data_array = []
		with open(self.stock_csv, 'r') as csvfile:
			stock_reader = csv.reader(csvfile)
			for row in stock_reader:
				logging.debug(str(row))
				data_array.append(row)

		# the first row will be keys, and the next rows will be actual stock data
		# zip the data into a convenient list of dicts
		keys = data_array[0]
		logging.debug("zipping stock data")
		for i in range (1, len(data_array)):
			stock_dict = dict(zip(keys, data_array[i]))
			stock_dict['targetBuy'] = float(stock_dict['targetBuy'])
			stock_dict['targetSell'] = float(stock_dict['targetSell'])
			stock_dict['weightTarget'] = float(stock_dict['weightTarget'])
			self.stock_list_of_dicts.append(stock_dict)


	# Get quotes of the stocks of interest from the ib interface
	def get_quotes(self):
		logging.debug("Getting quotes...")
		self.quote_list = []
		for stock in self.stock_list_of_dicts:
			quote_data = self.ibif.get_stock_quote(stock['ticker'])
			if quote_data['last'] is None:
				price = quote_data['close']
			else:
				price = quote_data['last']
			logging.debug('Last price of %s: %f', stock['ticker'], price)
			quote_data['ticker'] = stock['ticker']
			self.quote_list.append(quote_data)

	# Get current positions from the ib interface
	def get_positions(self):
		self.position_list = self.ibif.get_positions()
		logging.debug("Current holdings: " + str(self.position_list))

	# Update current orders, modifying or cancelling ones that require it
	def update_orders(self):
		# First, remove any orders that are no longer open
		open_list = self.ibif.get_open_order_ids()
		logging.debug('Open order ids: ' + str(open_list))
		self.put_order_list = [order for order in self.put_order_list if order['id'] in open_list]
		self.call_order_list = [order for order in self.call_order_list if order['id'] in open_list]
		logging.debug('Current put orders ' + str(self.put_order_list))
		logging.debug('Current call orders ' + str(self.call_order_list))

		# Then, iterate through open orders and leave, modify, or cancel them
		for order in self.put_order_list + self.call_order_list:
			status, filledQuant = self.ibif.get_order_status(order['id'])
			if status is not None:
				logging.debug('Order status is ' + str(status))
			else:
				logging.debug('Order did not return a status.  Must be closed already.')
				return
			if filledQuant > 0 and filledQuant < order['quantity']:
				self.handle_partial_fill(order)
				if order['right'] == 'P':
					self.put_order_list = [o for o in self.put_order_list if o['id'] != order['id']]
				else:
					self.call_order_list = [o for o in self.call_order_list if o['id'] != order['id']]
			elif status == 'submitted' or status == 'Submitted':
				self.modify_option_sell_order(order)
			# This will only happen if order has been filled between now and the ibif order check
			elif status == 'filled' or status == 'Filled':
				self.put_order_list = [o for o in self.put_order_list if o['id'] != order['id']]
			# If order status isn't submitted or filled then we should do nothing at this point
			else:
				logging.debug('Order not yet submitted. Doing nothing...')

	# Return the stock holdings for the given ticker
	def get_stock_holding(self, ticker):
		for position in self.position_list:
			if position['ticker'] == ticker and position['type'] == 'STK':
				return position
		return None

	# Return a list of option holdings for the current ticker
	def get_option_holdings(self, ticker):
		ret_list = [position for position in self.position_list if position['ticker'] == ticker and position['type'] == 'OPT']
		if ret_list:
			return ret_list
		else:
			return None

	# Extract a quote from the current quote list
	def get_current_quote(self, ticker):
		for quote in self.quote_list:
			if quote['ticker'] == ticker:
				return quote

	# Looping method to execute the trading strategy
	def trade_loop(self):
		logging.debug("In trade loop...")
		while self.trade:
			# Get data from the ib interface
			self.get_quotes()
			self.get_positions()
			# Update current orders
			self.update_orders()
			for stock in self.stock_list_of_dicts:
				ticker = stock['ticker']
				logging.debug("Executing strategy for " + ticker)
				# If we have open orders for this ticker, we should do nothing
				existing_order = False
				for order in self.put_order_list + self.call_order_list:
					if order['ticker'] == stock['ticker']:
						existing_order = True
						break
				if existing_order:
					logging.info('Order is open for %s. Moving on...', ticker)
					continue

				# At this point, no open orders. gather all the data we need to make a decision, and pass it to the decision making method
				logging.debug('No open orders for ' + ticker)
				# Retrieve position once more to ensure an order was not filled between our last update and now
				self.get_positions()
				stk_hold = self.get_stock_holding(ticker)
				opt_hold = self.get_option_holdings(ticker)
				quote = self.get_current_quote(ticker)
				self.trade_decision(stock, stk_hold, opt_hold, quote)
			time.sleep(10)

	# Make a decision on what to do with the given ticker
	def trade_decision(self, stock, stk_hold, opt_hold, quote):
		ticker = stock['ticker']
		if quote['last'] is None:
			price = quote['close']
		else:
			price = quote['last']
		# Determine how far away we are from targets
		buy_diff = (price - stock['targetBuy'])/stock['targetBuy']
		sell_diff = (stock['targetSell'] - price)/stock['targetSell']

		# Determine current call and put holdings
		call_hold = None
		put_hold = None
		put_exposure = 0
		call_exposure = 0
		if opt_hold:
			put_hold = [p for p in opt_hold if p['right'] == 'P']
			call_hold = [c for c in opt_hold if c['right'] == 'C']
		if put_hold:
			put_exposure = sum([p['quantity'] for p in put_hold])
		if call_hold:
			call_exposure = sum([c['quantity'] for c in call_hold])

		logging.debug('Current put exposure on %s: %d', ticker, put_exposure)
		logging.debug('Current call exposure on %s: %d', ticker, call_exposure)

		# Determine target quantity for positions.  Average into and out of positions based on the target weight
		if stock['weightTarget'] <= 300:
			# If target is 100 or 200, just do 1 contract (100 shares) at a time
			target_quantity = 1
		else:
			# Otherwise, handle the position in thirds, rounding up
			target_quantity = round(stock['weightTarget']/300.0 + .5)

		# if stk_hold is None and opt_hold is None:
		if stk_hold is None:
			if buy_diff < self.buy_thresh:
				if put_exposure == 0:
					self.sell_puts(stock, price, target_quantity)
				else:
					logging.debug('We are near price target, but we are already short puts on %s.  Doing nothing.', ticker)
					return
			else:
				logging.debug('We are not near the buy target for %s, and we do not have any shares. Doing nothing.', ticker)
				return

		# If we currently hold the stock
		else:
			# If current holdings between 0 and target holdings, sell more puts and sell matching strangle calls
			if stk_hold['quantity'] < stock['weightTarget']:
				if not call_hold:
					# Sell calls on all held shares.  Might change this to match the put quantity later, not set on it.
					self.sell_strangle_calls(stock, price, stk_hold['quantity']/100, stk_hold)
				if not put_hold:
					# Put quantity will either be the target quantity calculated earlier or the amount left until weight target hit, whichever is smaller
					# TEST
					exp1 = datetime.date(2017, 11, 24)
					q = self.ibif.get_option_quote('NUE', exp1, 'P', 55.5)
					print('After sell_strangle_calls exit', q)
					put_quantity = min((stock['weightTarget'] - stk_hold['quantity'])/100, target_quantity)
					self.sell_puts(stock, price, put_quantity)
				return

			# If current position is greater than or equal to weightTarget, and we are within sell threshold, sell calls
			elif call_exposure == 0 and sell_diff < self.sell_thresh:
				# Quantity of calls to sell will be the min of the currently held 100s of shares and the target quantity
				call_quantity = min(stk_hold['quantity']/100, target_quantity)
				self.sell_exit_calls(stock, price, call_quantity, stk_hold)
				return
		logging.info('Nothing to do for ' + ticker)

	# We run into an odd edge case when an order has partially filled.
	# I don't know what happens to a partially filled order when we attempt to modify it, and unfortunately
	# this is a very difficult situation for which to develop a test case.
	# So it seems best to cancel and re-send with new desired quantity, since we know exactly what will happen that way
	def handle_partial_fill(self, order):
		cancelled_flag, filled = self.ibif.cancel_order(order['id'])
		# check if the order was cancelled property, and get the final amount of contracts filled
		if cancelled_flag:
			new_quant = order['quantity'] - filled
		else:
			logging.error('Order was not cancelled properly.')
			if filled == order['quantity']:
				logging.error('Order was filled completely before cancellation. Returning...')
				return
			else:
				logging.error('Order was not completely filled, but something went wrong in cancellation. Returning...')
				return

		order['quantity'] = new_quant
		# copy dict for easy sending to ibif
		send_order = order.copy()
		del send_order['loop_cnt']
		del send_order['mod_cnt']
		del send_order['id']
		order['id'] = self.ibif.place_option_order(**send_order)
		order['loop_cnt'] = 0
		order['mod_cnt'] = 0
		if order['right'] == 'C':
			self.call_order_list.append(order)
		else:
			self.put_order_list.append(order)

	# Reduce asking price if appropriate.  Otherwise just increment loop cnt for the order, or cancel it
	def modify_option_sell_order(self, order_dict):
		loop_cnt = order_dict['loop_cnt']
		mod_cnt = order_dict['mod_cnt']
		# If this order shouldn't be modified yet
		if loop_cnt < self.loop_max:
			logging.debug('Order with id %d should not be modified yet', order_dict['id'])
			order_dict['loop_cnt'] = loop_cnt + 1
		# If it should be modified and hasn't hit the max modifications yet
		# To modify an order with the IB api, just resubmit with the same order id
		elif mod_cnt < self.mod_max:
			logging.debug('Modifying order with id %d', order_dict['id'])
			# decrement price by .01
			order_dict['price'] = order_dict['price'] - .01
			# copy dict for easy sending to ibif
			send_order = order_dict.copy()
			send_order['order_id'] = order_dict['id']
			del send_order['loop_cnt']
			del send_order['mod_cnt']
			del send_order['id']
			self.ibif.place_option_order(**send_order)
			order_dict['loop_cnt'] = 0
			order_dict['mod_cnt'] = mod_cnt + 1
		# If it has hit max mods, should be cancelled
		else:
			logging.debug('Order with id %d has been modified too many times.  Cancelling...', order_dict['id'])
			self.ibif.cancel_order(order_dict['id'])
			if order_dict['right'] == 'P':
				self.put_order_list = [o for o in self.put_order_list if o['id'] != order_dict['id']]
			else:
				self.call_order_list = [o for o in self.call_order_list if o['id'] != order_dict['id']]
			return True

		# If we get here, we need to modify the order list and return that the order has not been cancelled
		for order in self.put_order_list + self.call_order_list:
			if order['id'] == order_dict['id']:
				order['loop_cnt'] = order_dict['loop_cnt']
				order['mod_cnt'] = order_dict['mod_cnt']
				order['price'] = order_dict['price']
				return False

		logging.error('Order not found in the order list.  something went wrong...')
		return False
			
	# Sell puts for the given ticker
	def sell_puts(self, stock, stk_price, quantity):
		logging.info('Selling puts on ' + stock['ticker'])
		ticker = stock['ticker']
		# Find the best option strike and expiry
		target = self.search_for_option(ticker, stk_price, 'put', stock)
		# If we found a target, submit an order
		if target is not None:
			logging.info('Selling put on %s with strike %f and expiry %s for price %f', ticker, target['strike'], str(target['expiry']), target['price'])
			# append target dict for easy sending to ibif
			target['ticker'] = ticker
			target['quantity'] = int(quantity)
			target['right'] = 'P'
			target['action'] = 'SELL'
			order_id = self.ibif.place_option_order(**target)
			# append with bookkeeping attributes for order monitoring
			target['id'] = order_id
			target['loop_cnt'] = 0
			target['mod_cnt'] = 0
			self.put_order_list.append(target)
		else:
			logging.warning('No suitable put found to sell for %s', ticker)

	# Sell calls as part of a strangle. Called when we hold the stock but don't hold the target weight yet
	def sell_strangle_calls(self, stock, stk_price, quantity, stk_hold):
		ticker = stock['ticker']
		logging.info('Selling calls on ' + ticker + 'as part of a strangle')
		# TEST
		exp1 = datetime.date(2017, 11, 24)
		q = self.ibif.get_option_quote('NUE', exp1, 'P', 55.5)
		print('Before search for option', q)
		# Get available options expiries and sort them
		target = self.search_for_option(ticker, stk_price, 'strangle_call', stock, stk_hold)
		# TEST
		exp1 = datetime.date(2017, 11, 24)
		q = self.ibif.get_option_quote('NUE', exp1, 'P', 55.5)
		print('After search for option', q)
		# If we found a target, submit an order
		if target is not None:
			logging.info('Selling call on %s with strike %f and expiry %s for price %f', ticker, target['strike'], str(target['expiry']), target['price'])
			# append target dict for easy sending to ibif
			target['ticker'] = ticker
			target['quantity'] = int(quantity)
			target['right'] = 'C'
			target['action'] = 'SELL'
			order_id = self.ibif.place_option_order(**target)
			# append with bookkeeping attributes for order monitoring
			target['id'] = order_id
			target['loop_cnt'] = 0
			target['mod_cnt'] = 0
			self.call_order_list.append(target)
			# TEST
			exp1 = datetime.date(2017, 11, 24)
			q = self.ibif.get_option_quote('NUE', exp1, 'P', 55.5)
			print('At the end of sell strangle calls', q)
		else:
			logging.warning('No suitable strangle call found to sell for %s', ticker)

	# Sell calls to begin exiting a stock position. Will be called when target weight is equal to target quantity, and we are near sell target
	def sell_exit_calls(self, stock, stk_price, quantity, stk_hold):
		ticker = stock['ticker']
		logging.info('Selling calls on ' + ticker + ' to exit the position')
		target = self.search_for_option(ticker, stk_price, 'exit_call', stock, stk_hold)
		if target is not None:
			logging.info('Selling call on %s with strike %f and expiry %s for price %f', ticker, target['strike'], str(target['expiry']), target['price'])
			# append target dict for easy sending to ibif
			target['ticker'] = ticker
			target['quantity'] = int(quantity)
			target['right'] = 'C'
			target['action'] = 'SELL'
			order_id = self.ibif.place_option_order(**target)
			# append with bookkeeping attributes for order monitoring
			target['id'] = order_id
			target['loop_cnt'] = 0
			target['mod_cnt'] = 0
			self.call_order_list.append(target)
		else:
			logging.warning('No suitable strangle call found to sell for %s', ticker)

	# Find a suitable option contract for the given situation
	def search_for_option(self, ticker, stk_price, strategy, stock, stk_hold=None):
		date_list = self.ibif.get_expiries(ticker)
		# Only get expiries that are one month or less away
		date_list = [date for date in date_list if (date - datetime.datetime.now().date()).days <= 31]
		date_list.sort()
		logging.debug('Looking for options on the following dates: ' + str(date_list))
		# Set right to use for contracts
		if strategy == 'exit_call' or strategy == 'strangle_call':
			right = 'C'
		else:
			right = 'P'
		# Initialize target result to None
		target = None
		for expiry in date_list:
			logging.debug('On expiry ' + str(expiry))
			# Get available strikes
			strike_list = self.ibif.get_strikes(ticker, expiry)
			# find the best strike to use from the list.  Criteria changes based on the strategy being implemented
			strike = self.find_best_strike(stk_price, strike_list, strategy, stock, stk_hold)
			# Quote the selected option
			opt_quote = self.ibif.get_option_quote(ticker, expiry, right, strike)
			logging.debug('Quote for this option: ' + str(opt_quote))
			# offer = round((opt_quote['bid'] + opt_quote['ask'])/2.0)
			if all(value == None for value in opt_quote.values()):
				logging.error('Empty quote returned.  Possible problem with data connection. Skipping this strike')
				continue
			if opt_quote['last'] is None:
				offer = opt_quote['close']
			else:
				offer = opt_quote['last']
			# Check if price is good enough for the expiry
			days2exp = (expiry - datetime.datetime.now().date()).days
			# Target weeklies and bi-weeklies if the price is good enough
			logging.debug('Offer for strike %f: %f', strike, offer)
			if days2exp <= 4:
				if offer is not None:
					if offer >= .005*stk_price:
						target = {'expiry': expiry, 'strike': strike, 'price': offer}
					else:
						logging.debug('Price not good enough for weekly')
			elif days2exp <= 11:
				if offer is not None:
					if offer >= .008*stk_price:
						if target is None:
							target = {'expiry': expiry, 'strike': strike, 'price': offer}
							logging.debug('Bi-weekly fits criteria, and the weekly did not')
							break
						elif offer > 1.8*target['price']:
							target = {'expiry': expiry, 'strike': strike, 'price': offer}
							logging.info('The bi-weekly offer trumps the weekly offer')
							break							
					else:
						logging.debug('Price not good enough for bi-weekly')
						if target is not None:
							logging.debug('Executing weekly offer')
							break
			# if not, get the first available expiry with premium > 1% share price
			elif offer is not None:
				if offer >= .01*stk_price:
					target = {'expiry': expiry, 'strike': strike, 'price': offer}
					break
		return target

	# Find the most fitting strike from the given list for the given strategy
	def find_best_strike(self, stk_price, strike_list, strategy, stock, stk_hold=None):
		if strategy == 'strangle_call':
			cost = stk_hold['cost']
			if stk_price < cost:
				# If we have no unrealized profit, sell at first strike above cost of position
				return min(s for s in strike_list if s > cost)
			else:
				# If we have unrealized profit, sell at first strike above current price
				return min(s for s in strike_list if s > stk_price)
		elif strategy == 'exit_call':
			if stk_price > stock['targetSell']:
				# Highest ITM call if we are above target
				return max(s for s in strike_list if s < stk_price)
			else:
				# Lowest OTM call if we are below target
				return min(s for s in strike_list if s >= stk_price)
		elif strategy == 'put':
			if stk_price > stock['targetBuy']:
				# Highest OTM put if we are above target
				return max(s for s in strike_list if s <= stk_price)
			else:
				# Lowest ITM put if below target
				return min(s for s in strike_list if s > stk_price)

	# Shut down the option seller
	def shut_down(self):
		self.trade = False
		self.trade_thread.join()
		self.ibif.shut_down()


def main():
	try:
		ops = OptionSeller()
		while True:
			time.sleep(.1)
	except KeyboardInterrupt:
		logging.warning('Received keyboard interrupt.  Exiting gracefully...')
		ops.shut_down()
	except:
		logging.warning('Unexpected error. Shutting it down...')
		ops.shut_down()


if __name__ == '__main__':
	main()