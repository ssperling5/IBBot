BACKGROUND

I would like to start off with a disclaimer: I have not tested this code with real money. I've only run the Options Seller algorithm in Paper Trading. If you plan on using my API or the Options Seller algorithm in your own portfolio, I strongly urge you to do EXTENSIVE testing in paper trading before deploying it with real money. 

My motivation for this project was to implement a trading algorithm that integrates cash-secured puts and covered calls. The combination of these two plays is what I gravitated to after a few years of stock and options trading from 2015-2017. For more background on these strategies you can check out their pages on Options Education:

https://www.optionseducation.org/strategies/all-strategies/cash-secured-put#:~:text=The%20cash%2Dsecured%20put%20involves%20writing%20an%20at%2Dthe%2D,all%20outcomes%20are%20presumably%20acceptable.

https://www.optionseducation.org/strategies/all-strategies/covered-call-buy-write

The appeal of cash-secured puts is that you can basically earn income from putting in limit buy orders on a stock you like. Similarly, the appeal of a covered call is that you can earn income from putting in a limit sell order at a price you are comfortable exitting. The combination of these two strategies can turn your portfolio into a cash flow monster. This strategy would usually underperform simple buy and hold in a strong bull market, but it would outperform in a bear, sideways, or weak bull market. 

If you wanted you could execute this strategy on SPY, but it will likely perform better on individual stocks. Since individual stocks are more volatile than the index, you can collect more options premium by selling puts and calls. It also allows for greater diversification for midsize portfolios. Indiviudal stocks are often much cheaper than 1 share of SPY, and cash-secured puts and covered calls require enough cash to purchase the underlying in multiples of 100 due to the nature of options contracts.

As I mentioned earlier, I never did get a chance to test my algorithm with real money. It was right around the time that I completed the bulk of this project that I also lost interest in stocks and options in general. In late 2017 I began to shift my focus to real estate investment.


Interactive Brokers Interface

Interactive Brokers had been my broker of choice for a long time due to their cheap options commissions. I was in luck when I became interested in this project, since they also provide their API for free to account holders. Their API offers a lot of options, but I needed to create a wrapper API around it in order to use it to its fullest potential. Hopefully you can benefit from my wrapper API even if you do not like my Options Selling strategy. The native Interactive Brokers API was somewhat complicated to work with, and I did my best to comment extensviely in my wrapper API. Please don't hesitate to reach out to me with any questions that arise.
