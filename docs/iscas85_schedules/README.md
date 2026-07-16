# ISCAS'85 Scheduling Graphs

This directory contains generated IMPLY/FALSE scheduling graphs for the checked-in
ISCAS'85 benchmark circuits in `synthesis/circuits/ISCAS85`.

Each benchmark has a `<circuit>_schedule.svg` for GitHub preview and
documentation.

The graphs are generated from `synthesis/compiled/<circuit>/<circuit>.seq.txt`
using the repository renderer:

```bash
python3 synthesis/utils/render_schedule_svg.py \
  synthesis/compiled/c17/c17.seq.txt \
  docs/iscas85_schedules/c17_schedule.svg \
  --title "c17 ISCAS85 IMPLY/FALSE schedule"
```

Large benchmark graphs such as `c6288` are included for completeness, but they
are mainly useful as generated artifacts rather than as compact teaching figures.
