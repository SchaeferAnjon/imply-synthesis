# ISCAS'85 Scheduling Graphs

This directory contains generated IMPLY/FALSE scheduling graphs for the checked-in
ISCAS'85 benchmark circuits in `synthesis/circuits/ISCAS85`.

Each benchmark has:

- `<circuit>_schedule.svg` for GitHub preview and documentation.
- `<circuit>_schedule.drawio` for editing in diagrams.net / draw.io.

The graphs are generated from `synthesis/compiled/<circuit>/<circuit>.seq.txt`
using the repository renderer:

```bash
python3 synthesis/render_schedule_svg.py \
  synthesis/compiled/c17/c17.seq.txt \
  docs/iscas85_schedules/c17_schedule.svg \
  --drawio docs/iscas85_schedules/c17_schedule.drawio \
  --title "c17 ISCAS85 IMPLY/FALSE schedule"
```

Large benchmark graphs such as `c6288` are included for completeness, but they
are mainly useful as generated artifacts rather than as compact teaching figures.
