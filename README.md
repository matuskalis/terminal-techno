# Terminal Techno

A live techno sequencer that runs entirely in the terminal. Six tracks, 16 steps, four
pattern slots, everything synthesized in Python from scratch (no samples), with an ASCII
oscilloscope and spectrum analyzer reacting to the audio in real time.

```
  TERMINAL TECHNO  131.0 BPM   PAT A   ▶ PLAY   BAR 007  ────────────────────
      1 · · · 2 · · · 3 · · · 4 · · ·
 KCK  ■ · · · ■ · · · ■ · · · ■ · · ·   ████···· 1.00
 CLP  · · · · ■ · · · · · · · ■ · · ·   █······· 0.75
 HAT  ■ ■ ◆ ■ ■ ■ ◆ ■ ■ ■ ◆ ■ ■ ■ ◆ ■   ██······ 0.65
 OHT  · · ■ · · · ■ · · · ■ · · · ■ ·   █······· 0.55
 BAS  ◆ · · ■ · · ■ · ◆ · · ■ · · ■ ·   ███····· 0.90
 LED  ◆ · ■ ■~· · ■ ■ · · ◆ ■~· · ■ ■   ██······ 0.80
```

The block above is the real interface, not a mockup: six tracks down the left,
the 16-step grid, and each track's live level meter on the right.

## Run

```sh
git clone https://github.com/matuskalis/terminal-techno.git
cd terminal-techno
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

./run.sh                 # 130 BPM, default groove, starts stopped - hit space
./run.sh --bpm 145
./run.sh --list-devices
./run.sh --bounce out.wav --bars 8     # render to a file instead of playing
```

`--bounce` needs no audio device, so it also works over SSH and in CI.

Needs a terminal at least 60x24. Bigger terminal = taller scope and spectrum.

## Keys

| key | action |
| --- | --- |
| `space` | play / stop |
| `←` `→` / `h` `l` | move step cursor |
| `↑` `↓` / `k` `j` | move track cursor |
| `1`-`6` | jump to track |
| `x` / `enter` | toggle step on/off |
| `a` | accent step (louder, brighter filter, longer for BAS/LED) |
| `s` | slide step (BAS/LED only, glides into the next note) |
| `-` `=` | note down / up on the selected step (BAS/LED) |
| `,` `.` | BPM -1 / +1 (`<` `>` for ±5) |
| `[` `]` | arm previous / next board (lands on the next bar) |
| `shift`+`1`..`8` | arm board 1-8 directly |
| `t` | crossfade on/off (deck B = the armed board) |
| `9` `0` | fader toward A / toward B; reaching B commits the swap |
| `m` | mute selected track |
| `v` `V` | track volume down / up |
| `r` / `R` | randomize selected track / all tracks |
| `c` / `C` | clear selected track / all tracks |
| `f` `F` | acid filter cutoff down / up |
| `d` `D` | delay mix down / up |
| `z` `Z` | swing down / up (offbeat 16ths, 0-35%) |
| `w` | start / stop recording to `rec-<timestamp>.wav` |
| `o` | next output device |
| `O` | rescan devices, then open the system default (use after connecting Bluetooth) |
| `u` | mute / unmute the UI click sounds |
| `q` | quit |

Accents show as `◆`, plain steps as `■`, slides as `~` between two steps.

## Boards

Eight boards, each a full six-track scene. Four ship filled - `simple`, `peak`, `acid`, `dub` -
and boards 5-8 start empty for you to build with `r` and `x`.

Two ways to move between them:

- **Queued swap.** `[` `]` or `shift`+digit arms a board; the strip shows `(n)` and a countdown in
  steps, and the swap lands on the next bar line so the change is on the beat.
- **Crossfade.** `t` loads the armed board onto deck B and runs both boards at once. `9` and `0`
  move the fader (equal-power, so the level holds through the blend); reaching B commits - deck B
  becomes the live board and its voice tails ring on through the swap. `t` again cancels.

The strip reads `[n]` live, `(n)` armed, `<n>` on deck B. Editing always targets the live board.

## Tracks

| track | voice |
| --- | --- |
| KCK | sine kick with a pitch envelope and a noise click, soft-clipped |
| CLP | bandpassed noise clap, three bursts plus a tail |
| HAT | highpassed noise, 42 ms decay |
| OHT | same voice, 300 ms decay |
| BAS | saw + sub octave through a swept resonant lowpass, root A1 |
| LED | 303-style acid: saw/square, high-resonance filter sweep, glide, drive, root A2 |

LED and CLP feed a tempo-synced ping-pong delay (dotted eighth). Master bus is soft-clipped.

## Output device

The app opens the system default output at launch and re-checks every two seconds, so changing the
output in Sound settings moves the audio over on its own. A device that connects *after* launch
(Bluetooth headphones, a dock) is invisible to the audio layer until PortAudio is re-initialised -
press `O` for that. `o` steps through the devices found so far. All of it runs off the UI thread,
because opening a device that is not really there can block for ten seconds.

## Files

- `dsp.py` - voices (kick, clap, hats, bass, acid) and the ping-pong delay
- `engine.py` - boards, pattern data, step sequencer, two-deck mixer; `Engine.render(frames)` is what the audio callback calls
- `tui.py` - curses grid, meters, oscilloscope, spectrum, recording and device keys
- `techno.py` - CLI, `AudioOut` (stream + device switching), main loop

## Notes

- CPU is about 3-4% of realtime on an M-series Mac at 48 kHz / 1024-sample blocks.
- Pattern slots A-D all start with the same default groove; edit them independently and
  switch with `[` `]` while playing to arrange a track.
- Swing lengthens the downbeat 16th and shortens the offbeat, so the bar keeps its length.
- Key presses make a short tick, and a board landing or a committed crossfade makes a rising blip;
  `u` turns that off. Recording taps the mix before those ticks, so takes stay clean.
- Crossfading runs two full voice banks, about 4.7% of realtime CPU versus 3.4% for one.
- Playback starts automatically; `--stopped` launches paused.
- `--bounce` renders offline (faster than realtime) so you can capture a loop as a wav.
