from ib_insync import IB

ib = IB()
ib.connect('127.0.0.1', 4002, clientId=1)
print(next(v for v in ib.accountSummary() if v.tag == 'NetLiquidation'))
