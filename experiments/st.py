from maek import network, params
c=params.load_config(overlays=[params.scenario_path("steam")]); params.validate(c)
s,f,d=network.generate_network(c,seed=0)
print(network.summary(s,f,d)); print(s.medium.value_counts().to_dict(), f.kind.value_counts().to_dict())
print(d[d.zone_id.notna()].kind.value_counts().to_dict(), s.iloc[:3].T)
