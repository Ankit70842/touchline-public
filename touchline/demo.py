"""Original, deterministic fictional demo. No provider data, serialized models or fit."""
import math
import numpy as np


class DemoEstimator:
    """An explicitly illustrative rule, never a trained market-value estimator."""
    def predict(self, frame):
        return np.log1p(100000 + frame.minutes.to_numpy()*100 + frame.goals.to_numpy()*200000
                        + frame.assists.to_numpy()*100000)


def build_demo():
    from touchline.features import LEAGUES
    model=DemoEstimator()
    players=[];history={}
    leagues=list(LEAGUES)
    for i in range(12):
        value=100000+(900+i*90)*100+(i%7)*200000+(i%5)*100000
        previous=500000+i*125000
        p={'player_id':i+1,'name':f'Demo Player {i+1:02d}','club':f'Fictional Club {i%4+1}',
           'date':'2024-06-01','stats_through':'2024-05-20','age':20+i%10,
           'league':leagues[i%5],'league_name':LEAGUES[leagues[i%5]],
           'position':['Attack','Midfield','Defender','Goalkeeper'][i%4],
           'minutes':900+i*90,'appearances':20+i,'goals':i%7,'assists':i%5,
           'yellow_cards':0,'red_cards':0,'recent_minutes':180,'recent_goals':0,'recent_assists':0,
           'actual_value':previous+100000,'previous_value':previous,'previous_value_date':'2024-01-01',
           'previous_value_age_days':152,'predicted_value':value,'lower':round(value*.75),'upper':round(value*1.25),
           'valuation_aware_value':previous,'valuation_aware_lower':round(previous*.75),
           'valuation_aware_upper':round(previous*1.25),'valuation_aware_method':'previous_value',
           'goals_per90':round((i%7)*90/(900+i*90),4),'assists_per90':round((i%5)*90/(900+i*90),4)}
        # API uses log-symmetric illustrative bands; no empirical coverage claimed.
        for prefix,point in [('',value),('valuation_aware_',previous)]:
            p[prefix+'lower']=round(math.expm1(math.log1p(point)-.3))
            p[prefix+'upper']=round(math.expm1(math.log1p(point)+.3))
        players.append(p)
        history[str(i+1)]=[{'date':'2023-06-01','market_value_in_eur':previous*.8},
                           {'date':'2024-01-01','market_value_in_eur':previous},
                           {'date':'2024-06-01','market_value_in_eur':previous+100000}]
    metadata={'synthetic_demo':True,'source':{'appearances_through':'2024-05-20','valuations_through':'2024-06-01',
        'name':'Original synthetic fixtures; no real players or provider records'},
        'leagues':LEAGUES,'players':12,'positions':['Attack','Midfield','Defender','Goalkeeper']}
    evaluation={'evaluated':False,'selection':{'selected':'previous_value'},
        'note':'Previous-value baseline retained for demonstration. No validation scores or calibrated intervals are claimed.'}
    return {'bundle':{'model':model,'radius':.3},'update_bundle':{'selected':{'name':'previous_value','estimator':None},'radius':.3},
        'players':players,'history':history,'metadata':metadata,'evaluation':evaluation}
