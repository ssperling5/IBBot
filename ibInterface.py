# Helper functions for extracting data from TWS/gateway messages
from ib.ext.Contract import Contract
from ib.ext.Order import Order
from ib.opt import ibConnection, message

import time
import datetime
from threading import Thread
import signal

# python logging library for monitoring and debugging
import logging

# Set logging level
logging.basicConfig(format='%(levelname)s:%(message)s', level=logging.DEBUG)

# Reference codes for tick numbers on messages from TWS/Gateway
# Copied relevant codes ib.ext.TickType, can't get it to import properly for some reason
class TickTypes:
	BID = 1
	ASK = 2
	LAST = 4
	VOLUME = 8
	CLOSE = 9
	BID_OPTION = 10
	ASK_OPTION = 11
	LAST_OPTION = 12
	OPEN = 14
	OPEN_INTEREST = 22
	OPTION_IMPLIED_VOL = 24
	OPTION_CALL_OPEN_INTEREST = 27
	OPTION_PUT_OPEN_INTEREST = 28

# Class to provide a convenient wrapper around the TWS/Gateway message structure
class IbInterface:
	def __init__(self):
		# Values to be populated by the msg handlers when data received from TWS/Gateway
		self.account_value = None
		self.ticker = None
		self.key = None
		self.bid = None
		self.ask = None
		self.last = None
		self.volume = None
		self.close = None
		self.open_interest = None
		self.open = None
		self.order_status = None
		self.filled_quantity = None

		# list to hold possible options contracts, and ticker associated with contracts
		self.contract_list = []
		self.list_ticker = None

		# list to hold open order ids
		self.open_id_list = []

		# list to hold current positions, populated by the get positions method
		self.position_list = []

		# indicator that contract details, valid order id, open order id list, position details are ready
		self.detail_ready = False
		self.id_ready = False
		self.open_order_ready = False
		self.positions_ready = False

		# numeric identifier for market data request, contract detail request, placed order, and order for which status requested
		self.tick_id = 1
		self.detail_id = 1
		self.order_id = 0
		self.search_id = None

		# number of possible tick_id numbers and detail_id numbers
		self.id_max = 1000

		# timeout for quotes, in seconds, and counter for amount of ticks received for a quote
		self.quote_timeout = 10
		self.stk_tick_max = 5
		self.opt_tick_max = 5
		self.tick_cnt = 0

		# Connection to TWS/Gateway
		self.conn = ibConnection()

		# dict to neatly define function calls from the tick handler
		self.tick_callbacks = {
								TickTypes.BID : self._set_bid,
								TickTypes.ASK : self._set_ask,
								TickTypes.LAST : self._set_last,
								TickTypes.VOLUME : self._set_volume,
								TickTypes.CLOSE : self._set_close,
								TickTypes.BID_OPTION : self._set_bid,
								TickTypes.ASK_OPTION : self._set_ask,
								TickTypes.LAST_OPTION : self._set_last,
								TickTypes.OPEN : self._set_open,
								TickTypes.OPEN_INTEREST : self._set_open_interest,
								TickTypes.OPTION_IMPLIED_VOL : self._set_implied_vol,
								TickTypes.OPTION_CALL_OPEN_INTEREST : self._set_open_interest,
								TickTypes.OPTION_PUT_OPEN_INTEREST : self._set_open_interest
								}

		# Configure message handlers and connect
		self.conn.register(self._account_handler, 'UpdateAccountValue')
		self.conn.register(self._tick_handler, message.tickSize, message.tickPrice)
		self.conn.register(self._detail_handler, 'ContractDetails')
		self.conn.register(self._detail_end_handler, 'ContractDetailsEnd')
		self.conn.register(self._open_order_handler, 'OpenOrder')
		self.conn.register(self._open_order_end_handler, 'OpenOrderEnd')
		self.conn.register(self._order_status_handler, 'OrderStatus')
		self.conn.register(self._positions_handler, 'Position')
		self.conn.register(self._positions_end_handler, 'PositionEnd')
		self.conn.registerAll(self._order_id_handler)
		self.conn.connect()

	# Order id handler assignment is not working, so need to hack a way to extract valid id messages from All
	# Came up with very dirty triple exception hack. Use the fact that valid id messages have only a single key, orderId
	# Since other message types also have this key, we can cause exceptions on valid id message keys by trying to reference
	# aspects of the msg that don't exist for valid id messages.  Absolutely disgusting, but I'm proud of it in a grotesque way.
	def _order_id_handler(self, msg):
		# Excpetions in this first statement filter out messages with no order id
		# The if statement filters out messages that have an order id identitcal to current one
		# logging.debug('Message received: ' + str(msg))
		try:
			# if this is the first call, order_id will be none, so we need to account for this
			if self.order_id is not None:
				if msg.orderId == self.order_id:
					return
		except:
			return

		# filter out messages that have a valid status
		try:
			test = msg.status
		except:
			# filter out messages that have a valid contract
			try:
				test = msg.contract
			except:
				# only fresh valid id msg can be left at this point
				self.order_id = msg.orderId
				self.id_ready = True

	# reset data after it has been parsed to avoid double-reading
	def _reset_account_data(self):
		self.account_value = None

	# reset data after it has been parsed to avoid double-reading
	def _reset_tick_data(self):
		self.ticker = None
		self.key = None
		self.bid = None
		self.ask = None
		self.last = None
		self.volume = None
		self.open = None
		self.close = None
		self.open_interest = None

	# Handler for account information messages
	def _account_handler(self, msg):
		if msg.key=='NetLiquidation':
			self.account_value = msg.value

	# Handler for option/stock quote messages
	def _tick_handler(self, msg):
		# only handle messages associated with current tick id and for which we have callbacks
		if msg.field in self.tick_callbacks.keys() and msg.tickerId==self.tick_id:
			self.tick_callbacks[msg.field](msg)
			self.tick_cnt = self.tick_cnt + 1

	# Handler for contract detail messages
	def _detail_handler(self, msg):
		if msg.reqId==self.detail_id:
			self.contract_list.append(msg.contractDetails.m_summary)

	# Handler for the termination of contract details
	def _detail_end_handler(self, msg):
		self.detail_ready = True

	# Handler for open orders
	def _open_order_handler(self, msg):
		self.open_id_list.append(msg.orderId)	

	# Handler for the end of open order messages
	def _open_order_end_handler(self, msg):
		self.open_order_ready = True

	# Handler for order status messages
	def _order_status_handler(self, msg):
		if self.search_id is not None:
			if self.search_id == msg.orderId:
				self.filled_quantity = msg.filled
				self.order_status = msg.status

	# Handler for current position data
	def _positions_handler(self, msg):
		cont = msg.contract
		pos = {}
		pos['quantity'] = msg.pos
		pos['cost'] = msg.avgCost
		pos['ticker'] = cont.m_symbol
		pos['type'] = cont.m_secType
		if pos['type'] == 'OPT':
			pos['right'] = cont.m_right
			pos['expiry'] = datetime.datetime.strptime(cont.m_expiry, "%Y%m%d").date()
			pos['strike'] = cont.m_strike
		self.position_list.append(pos)

	# Handler for the end of position messages
	def _positions_end_handler(self, msg):
		self.positions_ready = True

	# Called from the tick handler when corresponding message received
	# Callbacks assigned in __init__
	def _set_bid(self, msg):
		self.bid = msg.price
	def _set_ask(self, msg):
		self.ask = msg.price
	def _set_open(self, msg):
		self.open = msg.price
	def _set_last(self, msg):
		self.last = msg.price
	def _set_close(self, msg):
		self.close = msg.price
	def _set_volume(self, msg):
		self.volume = msg.size
	def _set_implied_vol(self, msg):
		self.implied_vol = msg.size
	def _set_open_interest(self, msg):
		self.open_interest = msg.size

	# Construct option contract from given data
	def _make_option_contract(self, ticker, exp, right, strike):
		cont = Contract()
		cont.m_symbol = ticker
		cont.m_secType = 'OPT'
		cont.m_right = right
		cont.m_expiry = exp.strftime('%Y%m%d')
		cont.m_strike = float(strike)
		cont.m_exchange = 'SMART'
		cont.m_currency = 'USD'
		return cont

	# Construct a partial contract, in order to get available contracts for given ticker from TWS/Gateway
	def _make_partial_option_contract(self, ticker):
		cont = Contract()
		cont.m_symbol = ticker
		cont.m_secType = 'OPT'
		cont.m_exchange = 'SMART'
		cont.m_currency = 'USD'
		return cont

	# Construct stock contract from given data
	def _make_stock_contract(self, ticker):
		cont = Contract()
		cont.m_symbol = ticker
		cont.m_secType = 'STK'
		cont.m_exchange = 'SMART'
		cont.m_currency = 'USD'
		return cont

	# waits for all fields of a stock quote to be filled
	def _wait_for_stock_quote(self):
		# set timeout
		timeout = time.time() + self.quote_timeout
		# not thrilled with this way of waiting, but can't think of an alternative for now
		while(self.tick_cnt < self.stk_tick_max):
			time.sleep(.1)
			if time.time() > timeout:
				break

	# waits for all fields of an option quote to be filled
	def _wait_for_option_quote(self):
		# set timeout
		timeout = time.time() + self.quote_timeout
		# not thrilled with this way of waiting, but can't think of an alternative for now
		while(self.tick_cnt < self.opt_tick_max):
			# or self.implied_vol is None or self.open_interest is None):
			time.sleep(.1)
			if time.time() > timeout:
				break

	# Get all contracts available for given ticker
	def _get_contract_details(self, ticker):
		cont = self._make_partial_option_contract(ticker)
		logging.debug('Requesting details on ' + ticker)
		self.conn.reqContractDetails(self.detail_id, cont)
		logging.debug('Starting timeout timer for contract details')
		timeout = time.time() + 90
		while not self.detail_ready:
			time.sleep(.1)
			if time.time() > timeout:
				break
		logging.debug('Exiting contract details wait')
		self.detail_ready = False
		self.list_ticker = ticker
		self.detail_id = self.detail_id % self.id_max + 1

	# Get the next valid order id
	def _set_order_id(self):
		# request id and wait for it to be populated
		self.conn.reqIds(1)
		while not self.id_ready:
			time.sleep(.1)
		# reset the id_ready flag
		self.id_ready = False

	# Make an order to submit to TWS
	# For now automatically give everything Time-in-force of the day.  No reason to do good-til-cancel from an algo really.
	# Also, all orders will be limit orders.  Market orders from an algo sounds like the start of a horror story.
	def _make_order(self, action, price, quantity):
		order = Order()
		order.m_action = action
		order.m_lmtPrice = price
		order.m_totalQuantity = quantity
		order.m_orderId = self.order_id
		order.m_clientId = 0
		order.m_permid = 0
		order.m_auxPrice = 0
		order.m_tif = 'DAY'
		order.m_transmit = True
		order.m_orderType = 'LMT'
		return order

	# EXPOSED METHODS
	# returns account value as a float
	def get_account_value(self):
		self.conn.reqAccountUpdates(1, '')
		while(self.account_value is None):
			time.sleep(.1)
		acct_val = self.account_value
		self._reset_account_data()
		return acct_val

	# returns a dict of stock quote data
	def get_stock_quote(self, ticker):
		# create contract for mkt data request, and send request
		cont = self._make_stock_contract(ticker)
		self.tick_cnt = 0
		self.conn.reqMktData(self.tick_id, cont, '', False)

		# wait for data fields to be populated by msg handlers
		self._wait_for_stock_quote()
		quote_dict = {
					'bid' : self.bid,
					'ask' : self.ask,
					'last' : self.last,
					'volume' : self.volume,
					'close' : self.close
		}

		# Cancel current mkt data request and increment tick id
		self.conn.cancelMktData(self.tick_id)
		self.tick_id = self.tick_id % self.id_max + 1

		# reset tick data fields to None, and return quote
		self._reset_tick_data()
		self.tick_cnt = 0

		# if all fields are None, log an error
		# for now don't change return value.  later possible return None in this case, not sure
		if all(value == None for value in quote_dict.values()):
			logging.error('No option data found. Could be a problem with data servers.')

		return quote_dict

	# returns a dict of option quote data
	def get_option_quote(self, ticker, date, right, strike):
		logging.debug('Received quote request with the following data: ' + str(locals()))
		# create option contract for data request, and send request
		cont = self._make_option_contract(ticker, date, right, strike)
		self.tick_cnt = 0
		self.conn.reqMktData(self.tick_id, cont, '', False)

		# wait for data fields to be populated by msg handlers
		self._wait_for_option_quote()
		quote_dict = {
					'bid' : self.bid,
					'ask' : self.ask,
					'last' : self.last,
					'close' : self.close,
					'open' : self.open,
					'volume' : self.volume,
		}

		# Cancel current mkt data request and increment tick id
		self.conn.cancelMktData(self.tick_id)
		self.tick_id = self.tick_id % self.id_max + 1

		# reset tick data fields to None, and return quote
		self._reset_tick_data()
		self.tick_cnt = 0

		# if all fields are None, log an error
		# for now don't change return value.  later possible return None in this case, not sure
		if all(value == None for value in quote_dict.values()):
			logging.error('No option data found. Could be a problem with data servers.')

		return quote_dict

	# Returns possible expiries for given ticker
	# Dates will be returned in string format, wasn't certain whether to use date or str
	# Decided on date since user-end operations will likely be on date objects, and returning dates improves encapsulation
	# (Be careful not to spell get_expires by accident)
	def get_expiries(self, ticker):
		# If the ticker is not already stored, then we need to get contracts again
		# Otherwise the cached contracts apply to this ticker, and we need not get new data
		if ticker != self.list_ticker:
			self._get_contract_details(ticker)
		# Extract unique dates from the contract details list (crazy pythonic method)
		return list(set([datetime.datetime.strptime(c.m_expiry, "%Y%m%d").date() for c in self.contract_list]))

	# Return strikes available for given expiry.  Expiry input must be date for consistency with get_expiries method
	def get_strikes(self, ticker, expiry):
		# Convert the date input to a string.  Error if wrong type
		if type(expiry) is datetime.date:
			exp_str = expiry.strftime('%Y%m%d')
		else:
			logging.error('In get_strikes: Unrecognized expiry type %s, returning None.', str(e_type))
			return None

		# If the ticker is not already stored, then we need to get contracts again
		# Otherwise the cached contracts apply to this ticker, and we need not get new data
		if ticker != self.list_ticker:
			self._get_contract_details(ticker)
		# Extract strikes for which the contract expiry matches the given (crazy pythonic method)
		return list(set([c.m_strike for c in self.contract_list if c.m_expiry == exp_str]))

	# Place limit order for options contract
	# Recommend using keyword argument entry for this method, there are many inputs
	# action must be 'BUY' or 'SELL'
	# If no order id is supplied, the interface automatically gets the next valid order id to use
	# Supplying an order_id manually is not recommended.  If you'd like to modify an existing order, you should use the modify_option_order command
	def place_option_order(self, action, ticker, expiry, right, strike, price, quantity, order_id=None):
		logging.debug('Received order request with the following data: ' + str(locals()))
		# Check args
		if action != 'BUY' and action != 'SELL':
			logging.error('Unrecognized action %s. Action must be BUY or SELL. Returning None', str(action))
			return None
		if right != 'P' and right != 'C':
			logging.error('Unrecognized right %s. Right must be P or C. Returning None', str(right))
			return None

		# get valid order id
		if order_id is None:
			self._set_order_id()
			order_id = self.order_id

		# Compile arguments into dict for order storage
		order_dict = dict(locals())
		del order_dict['self']
		order_dict['order_id'] = order_id

		# first make the contract and the order
		order = self._make_order(action, price, quantity)
		cont = self._make_option_contract(ticker, expiry, right, strike)
		self.conn.placeOrder(order_id, cont, order)

		# return order_id as a handle to this order, and increment current order id
		return order_id

	# Get order status of order with id order_id
	# Returns a two item list with a string status and int order_quantity
	def get_order_status(self, order_id):
		# reset order status, and search for order with id order_id
		self.order_status = None
		self.search_id = order_id
		time.sleep(1)
		self.conn.reqOpenOrders()
		timeout = time.time() + 10
		while self.order_status is None:
			time.sleep(.1)
			if time.time() > timeout:
				logging.error('Order status timed out.  Order must have been filled or cancelled already')
				return None, None
		self.search_id = None
		return self.order_status, self.filled_quantity

	# Get a list of all current holdings
	def get_positions(self):
		logging.debug('Requesting positions...')
		self.conn.reqPositions()
		while not self.positions_ready:
			time.sleep(.1)
		self.positions_ready = False
		ret_list = self.position_list
		self.position_list = []
		return ret_list

	# Get quantity of a single stock position
	def get_stock_position(self):
		pos_list = self.get_positions()

	# Get a list of open order ids
	def get_open_order_ids(self):
		self.open_id_list = []
		self.open_order_ready = False
		self.conn.reqOpenOrders()
		timeout = time.time() + 10
		while not self.open_order_ready:
			if time.time() > timeout:
				logging.error('Open order id request timed out.  List may be incomplete')
				break
			time.sleep(.1)
		return list(set(self.open_id_list))

	# Cancel single order with order_id
	def cancel_order(self, order_id):
		self.conn.cancelOrder(order_id)
		timeout = time.time() + 60
		logging.debug('starting order cancel check')
		while True:
			logging.debug('getting order status')
			status, filled = self.get_order_status(order_id)
			if status is None:
				logging.info('Order returned no status.  Must already be filled or cancelled.')
				return False, None
			if status == 'cancelled' or status == 'Cancelled':
				logging.info('Order cancelled successfully.')
				if filled is not None:
					logging.info('Filled quantity was %d', filled)
				return True, filled
			elif status == 'filled' or status == 'Filled':
				logging.info('Order was filled before it could be cancelled.')
				if filled is not None:
					logging.info('Filled quantity was %d', filled)
			if time.time() > timeout:
				logging.info('Order cancel timed out. Order has not been confirmed for cancel.')
				if filled is not None:
					logging.info('Filled quantity was %d', filled)
				return False, filled
			time.sleep(.1)


	# Cancel all open orders
	def cancel_all_orders(self):
		self.conn.reqGlobalCancel();

	# Shut down the interface
	def shut_down(self):
		logging.info('Shutting down interface.')
		return None

# test main
def main():
	try:
		ibif = IbInterface()
		exp = datetime.date(2017, 12, 1)
		ibif.place_option_order(action='SELL', ticker='NUE', right='P', strike=56.0, quantity=1, expiry=exp, price=1.0)
		time.sleep(5)
		id_list = ibif.get_open_order_ids()
		print(id_list)
		print(str(ibif.get_order_status(125)))
		for oid in id_list:
			print(str(ibif.get_order_status(oid)))
	except:
		ibif.shut_down()

if __name__ == '__main__':
	main()