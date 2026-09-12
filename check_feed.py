from pair_universe import PROP_SYMBOLS, MarketDataSource

mds = MarketDataSource()
print("Prop Symbols Loaded:", PROP_SYMBOLS)

for symbol in PROP_SYMBOLS[:3]:
    candles = mds.fetch_5m_candles(symbol, min_candles=10)
    print(f"Symbol: {symbol} | Candles fetched: {len(candles)}")
