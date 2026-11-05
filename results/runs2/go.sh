#!/bin/bash
cd /home/user/maek-strategy-v3
SP=/tmp/claude-0/-home-user/72a7cc9d-958e-56f6-8685-798eb6ea44d6/scratchpad/runs2
export OMP_NUM_THREADS=1
t() { local n=$1; shift; local s=$(date +%s); python -m maek "$@" > $SP/$n.txt 2>&1; echo "$n $(( $(date +%s) - s ))s" > $SP/$n.time; }
t base strategy --runs 10 --seed 1 --out $SP/base &
t steam strategy --scenario steam --runs 20 --seed 1 --out $SP/steam &
t pit pit-prior --runs 10 --seed 1 --total-km 100 --out $SP/pit &
t sweep sweep --runs 5 --total-km 20 --seed 1 --out $SP/sweep &
wait
echo done > $SP/ALLDONE
