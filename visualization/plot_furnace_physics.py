import csv,json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
p=Path('D:/obsd/Projects/hackerton/MAEK/visualization')
r=[{k:float(v) for k,v in a.items()} for a in csv.DictReader((p/'furnace_physics_trace.csv').open())];t=[a['time_s'] for a in r]
plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
fig,ax=plt.subplots(3,2,figsize=(12,10),constrained_layout=True)
for a in ax.flat:a.grid(alpha=.2);a.set_xlabel('Simulation time (s)')
ax[0,0].plot(t,[a['temperature_K']-273.15 for a in r],color='#c45a34');ax[0,0].set(title='Calculated bulk temperature',ylabel='Temperature (C)')
ax[0,1].plot(t,[a['produced_kg']/1000 for a in r],color='#337e79');ax[0,1].set(title='Net iron production from reactions',ylabel='Produced iron (t)')
ax[1,0].plot(t,[a['tap_kg_s'] for a in r],color='#b64436');ax[1,0].set(title='Pressure / head / resistance driven tapping',ylabel='Mass flow (kg/s)');ax[1,0].axvline(30,ls=':',color='gray');ax[1,0].axvline(400,ls=':',color='gray')
ax[1,1].plot(t,[a['iron_liquid_kg']/1000 for a in r],color='#446b95');ax[1,1].set(title='Liquid hearth inventory',ylabel='Liquid iron (t)')
ax[2,0].plot(t,[a['tapped_kg']/7000 for a in r],label='Taphole volume',color='#b64436',lw=3);ax[2,0].plot(t,[a['runner_m3']+a['outlet_m3'] for a in r],label='Runner + received',ls='--',color='#337e79');ax[2,0].set(title='Conservative transfer through the runner',ylabel='Volume (m3)');ax[2,0].legend()
x=[(k+.5)*.5 for k in range(48)]
for sec in (60,180,600):ax[2,1].plot(x,[r[sec]['h'+str(k)] for k in range(48)],label=str(sec)+' s')
ax[2,1].set(title='Solved free-surface depth profiles',xlabel='Distance along runner (m)',ylabel='Liquid depth (m)');ax[2,1].legend()
fig.suptitle('MAEK numerical demonstration — net reactions + enthalpy + 1D molten-iron flow\nIllustrative operating inputs; pure-iron proxy; not industrial calibration',fontsize=13)
fig.savefig(p/'furnace_physics_verification.png',dpi=160)
summary={'trace_seconds':600,'trace_rows':len(r),'tap_open_seconds':[30,400],'generated_iron_kg':r[-1]['produced_kg'],'tapped_kg':r[-1]['tapped_kg'],'received_kg':r[-1]['outlet_m3']*7000,'remaining_runner_kg':r[-1]['runner_m3']*7000,'max_transfer_residual_kg':max(abs(a['tapped_kg']-7000*(a['runner_m3']+a['outlet_m3'])) for a in r)}
(p/'furnace_trace_summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary))
