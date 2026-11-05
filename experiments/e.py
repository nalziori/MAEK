from maek import network, params, energy
c=params.load_config(overlays=[params.scenario_path("steam")])
s,f,d=network.generate_network(c,seed=0)
l=energy.losses(c,s,d); print(l.groupby("kind")[["loss_kw","mwh_per_yr","cost_krw_per_yr"]].sum().round(1)); print(l[["mwh_per_yr","cost_krw_per_yr","co2_t_per_yr"]].sum())
