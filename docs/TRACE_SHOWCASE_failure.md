# NetHack honest-navigation harness — a FAILING game (diagnosed)

**What this is.** A companion to the successful floor-4 trace: one complete episode where the same GLM-5.2 agent **fails** to beat its seed — and *why*. It is the common failure mode behind the 3/6 ceiling. Same harness: raw map only, no `find`, no `descend` skill, no located-object hints.

## Verdict: descends one floor, then loops on floor 2 until the clock runs out

- **Reached floor 2, never floor 4.** Ran the full **299-turn** budget.
- **229 of 299 turns were spent stuck on floor 2.**
- **This is NOT a perception failure.** The down-stair `>` is visible on the map in **229 / 229** of the floor-2 turns, and the model repeatedly *says* it sees it (e.g. *"I can see '>' at (20,..)"*).
- **It is a path-execution / looping failure.** On floor 2 the model visited only 49 distinct tiles but revisited a handful over and over:

  | tile | times revisited |
  |---|---|
  | (40,7) | 38× |
  | (31,13) | 25× |
  | (40,10) | 21× |
  | (31,15) | 16× |
  | (40,8) | 13× |

- **It re-derives the same dead intent.** At turn 71 and again at turn 161 — 90 turns apart — the model emits the *identical* plan: *"I'm at (43,13). I need to go north through the corridor."* It is not building on prior steps; it is stuck in a loop.
- **Cost of looping:** HP bled from 250 to ~150 as monsters chipped away while it oscillated.

**Read this as:** the model *perceives the goal correctly* but cannot reliably execute the multi-step path to it — it hits a wall, re-plans from scratch, and re-enters the same loop. That is the consistency gap the best-of-N sweep is meant to probe: the ability is there (see the floor-1 descent below); the reliable execution is not.

---


## ▼ DoD 1 — the descent that WORKS  (turn 1, dlvl 1)

```
Velkommen Agent, welcome to NetHack!  You are a neutral human Valkyrie.

                    --------           ---------------
                    |......|          #+..........>...#
                    |.{....|          #|..:..........|#
                    |......|         ##---------------#
                    |......|         #       ##       #
               #####.......|       ###        #       #
       ------- #    --.-----       #          #############
       |......##      ###          #                #-----.--           ------
       |.....|          #          #                #|.....:|          #.....|
       |.....|          #          #                #+......-#####      |..@.|
       |.....|          ###        #                 |......|    #######-..d.|
       -------            #        #          #######|......|           |....|
                     -----.------- ############      |......|           ---+--
                     |............###      ##########.......|              #
                     |...........| # #######         --------
                     |............####
                     |...........| #
                     |...........+#
                     -------------
```

**T1** · floor 1 · (75,10) · hp 250

```python
print("=== MAP ===")
for y, row in enumerate(nh.map.rows):
    print(row)
print("\n=== PLAYER ===")
print(nh.under_player)
print("\n=== STATUS ===")
print(nh.status)
print("\n=== INVENTORY ===")
print(nh.inventory)
print("\n=== CHARACTER ===")
print(nh.character)
```

**T2** · floor 1 · (75,10) · hp 250

```python
print("=== UNDER PLAYER ===")
print(nh.under_player)
print("\n=== STATUS ===")
print(nh.status)
print("\n=== ADJACENT ===")
print(nh.adjacent)
```

**T3** · floor 1 · (75,11) · hp 250
> I can see a '>' (down stairs) at position (50, 2) on the map. There's a dog nearby but with 250 HP it's not a threat. Let me navigate toward the stairs.

```python
# First let me kill the adjacent dog, then move to stairs
nh.attack(direction="S")
```

**T4** · floor 1 · (74,11) · hp 250

```python
# Navigate to the '>' stairs at approximately (49, 2)
nh.move_to(49, 2)
```

**T5** · floor 1 · (75,12) · hp 250

```python
# The '>' is at (49, 2). I need to navigate there. Let me try autoexplore first.
nh.autoexplore()
```

**T6** · floor 1 · (74,12) · hp 250

```python
# Autoexplore hit a locked door. Let me try move_to the stairs directly
nh.move_to(50, 2)
```

**T7** · floor 1 · (74,12) · hp 250

```python
# Let me check what's around me and try to find a path
print("=== UNDER PLAYER ===")
print(nh.under_player)
print("\n=== NEIGHBORS ===")
print(nh.map.neighbors())
```

**T8** · floor 1 · (74,9) · hp 250

```python
# I need to navigate to '>' at (49, 2). Let me try going north first, then west through corridors.
# I'm at (74,12). Let me go north to (74,11) then continue north/west
nh.move(direction="N")
```

**T9** · floor 1 · (73,10) · hp 250

```python
# Try to move directly to the stairs at (50, 2)
nh.move_to(50, 2)
```

**T10** · floor 1 · (72,9) · hp 250

```python
# Let me try move_to the stairs again, it might find a longer path
nh.move_to(49, 2)
```

**T11** · floor 1 · (72,9) · hp 250

```python
# Let me check neighbors to understand where I can go
print(nh.map.neighbors())
```

**T12** · floor 1 · (71,9) · hp 250

```python
# I can go west through corridor at (71,9). Let me head west to find the path to '>' room.
nh.move(direction="W")
```

**T13** · floor 1 · (71,9) · hp 250

```python
# Try to navigate to the '>' stairs
nh.move_to(49, 2)
```

**T14** · floor 1 · (71,9) · hp 250

```python
# Check neighbors at current position
print(nh.map.neighbors())
print("\nPlayer position:", nh.map.player)
```

**T15** · floor 1 · (72,9) · hp 250

```python
# I'm at (71,9). To the west is solid stone. I need to go back east into the room 
# and find another exit. Let me go east first.
nh.move(direction="E")
```

**T16** · floor 1 · (72,9) · hp 250

```python
# I'm at (72,9). I see a '+' door at around (65,10) that was locked. Let me go south first and try to kick it open.
# But first let me check: maybe I should go through the room southward. 
# Let me try going south.
nh.move(direction="S")
```

**T17** · floor 1 · (72,9) · hp 250

```python
# Check neighbors at current position (72,9)
print(nh.map.neighbors())
```

**T18** · floor 1 · (76,9) · hp 250

```python
# Let me move east to explore the room and find the bottom door
nh.move(direction="E")
```

**T19** · floor 1 · (75,10) · hp 250

```python
# I'm at (76,9). The '>' is at around (50,2). Let me try move_to to navigate there.
nh.move_to(50, 2)
```

**T20** · floor 1 · (75,10) · hp 250

```python
# Let me check neighbors to find a way out of this room
print(nh.map.neighbors())
```

**T21** · floor 1 · (74,10) · hp 250

```python
# I need to go west to find the '+' door at around (52,10). Let me move west.
nh.move(direction="W")
```

**T22** · floor 1 · (73,10) · hp 250

```python
# Keep going west through the room to reach the '+' door
nh.move(direction="W")
```

**T23** · floor 1 · (73,10) · hp 250

```python
# Keep going west toward the '+' door
nh.move(direction="W")
```

**T24** · floor 1 · (73,10) · hp 250

```python
# I'm stuck in a small room. Let me check neighbors to find the exit
print(nh.map.neighbors())
```

**T25** · floor 1 · (73,10) · hp 250

```python
# I'm in a small room. I need to find my way to '>' which is at approximately (38, 1).
# Let me try move_to to navigate there
nh.move_to(38, 1)
```

**T26** · floor 1 · (73,9) · hp 250

```python
# I'm stuck in a room. Let me go north to find another exit
nh.move(direction="N")
```

**T27** · floor 1 · (73,9) · hp 250

```python
# I'm at (73,9). Let me check neighbors to find the exit
print(nh.map.neighbors())
```

**T28** · floor 1 · (71,9) · hp 250

```python
# I can go W to (72,9) which is floor. Let me go west.
nh.move(direction="W")
```

**T29** · floor 1 · (71,9) · hp 250

```python
# I'm at (71,9). I need to get to '>' at (50,2). 
# Looking at the map, there's a '+' door at approximately (53,10) on the west wall.
# Let me try to move to that door.
nh.move_to(53, 10)
```

**T30** · floor 1 · (71,9) · hp 250

```python
# I'm at (71,9) in the rightmost room. I need to get to '>' at (51,2).
# My room has a '+' door at approximately (75,13) in the south wall.
# Let me move south toward the door.
nh.move(direction="S")
```

**T31** · floor 1 · (71,9) · hp 250

```python
# Still at (71,9). South is solid stone. Let me check neighbors again.
print(nh.map.neighbors())
```

**T32** · floor 1 · (71,9) · hp 250

```python
# I'm stuck at (71,9) with walls and unseen rock around me. 
# I need to search for hidden passages or try to go through unseen areas.
# Let me search for hidden doors/passages.
nh.search(times=10)
```

**T33** · floor 1 · (71,9) · hp 250

```python
# Let me get exact positions of key features
map_rows = [
  "",
  "                    --------           ---------------",
  "                    |......|          #+..........>...#",
  "                    |.{....|          #|.......:.....|#",
  "                    |......|         ##---------------#",
  "                    |......|         #       ##       #",
  "               #####.......|       ###        #       #",
  "       ------- #    --.-----       #          #############",
  "       |......##      ###          #                #-----.--           ------",
  "       |.....|          #          #                #|......|          @..d..|",
  "       |.....|          #          #                #+......-#####      |d.<.|",
  "       |.....|          ###        #                 |......|    #######:d.^.|",
  "       |.....|          #        #          #######|......|           |....|",
  "       -------            #        #          ############      |......|           ---+--",
  "                     |............###      ##########.......|              #",
  "                     |...........| # #######         --------",
  "                     |............####",
  "                     |...........| #",
  "                     |...........+#",
  "                     -------------",
  ""
]

# Find '>' position
for y, row in enumerate(map_rows):
    for x, ch in enumerate(row):
        if ch == '>':
            print(f"> at ({x},{y})")
        if ch == '<':
            print(f"< at ({x},{y})")
        if ch == '+':
            print(f"+ (door) at ({x},{y})")

print(f"\nPlayer at {nh.map.player}")
print(f"\nUnder player: {nh.under_player}")
```

**T34** · floor 1 · (71,9) · hp 250

```python
# I see a '+' door at (86,13) in the south wall of my room. Let me try to navigate there.
# Also there's a door at (68,10) that connects to a corridor going right.
# Let me try moving to (86,13) first - that's the door in my room's south wall.
nh.move_to(86, 13)
```

**T35** · floor 1 · (73,9) · hp 250

```python
# I'm stuck in a small area. Let me try to move east (toward the little dog) 
# to see if I can get past it or attack it, then find the '+' door in the south wall.
# First let me attack the dog to the east.
nh.attack(direction="E")
```

**T36** · floor 1 · (73,10) · hp 250

```python
# I'm at (73,9). The '+' door is at (73,10) directly south. Let me try to move south through it.
nh.move(direction="S")
```

**T37** · floor 1 · (73,10) · hp 250

```python
# I'm at (73,10) now. Let me try to navigate to '>' at (50,2).
nh.move_to(50, 2)
```

**T38** · floor 1 · (73,10) · hp 250

```python
# move_to didn't work. Let me try moving west toward the '>' step by step.
# I'm at (73,10). I need to go west through the room and then find the corridor going north.
nh.move(direction="W")
```

**T39** · floor 1 · (73,12) · hp 250

```python
# I'm at (73,10), wall to west. I see a '+' door at (76,13) in the south wall of this room.
# I also see '<' (up stairs) at (75,10) but I need '>' (down stairs) at (50,2).
# Let me go south through the room to reach the '+' door at (76,13).
nh.move(direction="S")
```

**T40** · floor 1 · (73,12) · hp 250

```python
# I'm at (73,12). I need to go west through the room to reach the corridor.
# The room I'm in has walls. Let me check neighbors.
print(nh.map.neighbors())
```

**T41** · floor 1 · (75,10) · hp 250

```python
# I can go NE to (74,11) or E to (74,12). Let me go NE then try to find the path west.
nh.move(direction="NE")
```

**T42** · floor 1 · (75,10) · hp 250

```python
# I'm at (75,10) now. I need to go west through the room to reach the '+' door at (76,10).
# Wait, the '+' is at (76,10) to my east. But I need to go WEST to reach the '>' at (50,2).
# Let me check what's to the west.
print(nh.map.neighbors())
```

**T43** · floor 1 · (74,11) · hp 250

```python
# I'm at (75,10) in the rightmost room. West is floor at (74,10). 
# I need to go west through the corridor to reach '>' at (50,2).
# Let me try move_to to navigate there.
nh.move_to(50, 2)
```

**T44** · floor 1 · (74,11) · hp 250

```python
# I'm at (74,11). I see a '+' door at (76,10) to the NE and a corridor at (73,11) to the west.
# Let me check neighbors.
print(nh.map.neighbors())
```

**T45** · floor 1 · (73,11) · hp 250

```python
# I'm at (74,11). West is (73,11) floor. I need to go west through the corridor.
# Let me trace: the corridor at row 11 goes west through ####### then connects to a room.
# Let me go west step by step.
nh.move(direction="W")
```

**T46** · floor 1 · (72,11) · hp 250

```python
# I'm at (73,11). Let me continue west through the corridor toward the '>' at (50,2).
nh.move(direction="W")
```

**T47** · floor 1 · (66,11) · hp 250

```python
# I'm at (72,11). I see a 'd' (little dog) at (73,11) to my east - that's my pet, don't attack.
# Let me continue west through the corridor. 
nh.move(direction="W")
```

**T48** · floor 1 · (65,11) · hp 249

```python
# I'm at (66,11). The '>' is at (50,2) approximately. Let me check the map more carefully.
# Looking at row 2: #+..........>...#  - the '>' is at position (38,2) roughly.
# Let me count: row 2 starts with spaces, then #+..........>...#
# Position 20 is '#', 21 is '+', then dots until '>' 
# Let me count: positions 22-32 are dots (11 dots), then '>' at 33
# Actually let me just try move_to
nh.move_to(38, 2)
```

**T49** · floor 1 · (65,11) · hp 249

```python
# I'm at (65,11). The '>' is at approximately (51,2). I need to continue west through the corridor.
# There's a grid bug to my west - let me kill it then continue.
nh.attack(direction="W")
```

**T50** · floor 1 · (65,11) · hp 249

```python
# West is solid stone. Let me check all neighbors to find the right path.
print(nh.map.neighbors())
print("\nPlayer:", nh.map.player)
print("Under:", nh.under_player)
```

**T51** · floor 1 · (64,10) · hp 249

```python
# I can go NW to (64,10) which is corridor. Let me go that way toward the '>'.
# First kill the grid bug to the north, or just go NW.
nh.move(direction="NW")
```

**T52** · floor 1 · (64,10) · hp 249

```python
# I'm at (64,10). I need to get to '>' at (50,2). Looking at the map:
# Row 9: #+.....:-###@x      |..<.|
# I see a ':' at (57,9) which might be a shop or special. 
# The corridor goes west. Let me try move_to to the '>' position.
# First let me count the exact position of '>' in row 2.
row2 = "                    |......|          #+..........>...#"
for i, ch in enumerate(row2):
    if ch == '>':
        print(f"> at x={i}")
# Also find '<' positions
for i, ch in enumerate(row2):
    if ch == '<':
        print(f"< at x={i}")
```

**T53** · floor 1 · (63,10) · hp 249

```python
# '>' is at (50, 2). I'm at (64, 10). I need to navigate west and north.
# The corridor goes west from here. Let me try move_to(50, 2).
nh.move_to(50, 2)
```

**T54** · floor 1 · (62,10) · hp 249

```python
# I'm at (63,10). The grid bug keeps biting. Let me keep going west toward the '>' at (50,2).
nh.move_to(50, 2)
```

**T55** · floor 1 · (61,10) · hp 250

```python
# I'm at (62,10). There's a '+' door at (58,10) to my west. 
# The '>' is at (50,2) inside a room with a '+' door at (51,2).
# I need to get through the '+' door at (58,10), then navigate to the room with '>'.
# Let me keep going west.
nh.move(direction="W")
```

**T56** · floor 1 · (60,10) · hp 250

```python
# I'm at (61,10). Keep going west toward the '+' door and the '>' room.
nh.move(direction="W")
```

**T57** · floor 1 · (60,10) · hp 250

```python
# I'm at (60,10). I see a ':' at (59,10) to my west - that's a shop or special tile.
# The '+' door is at (58,10). Let me move west to the '+' door.
nh.move(direction="W")
```

**T58** · floor 1 · (59,10) · hp 250

```python
# Still at (60,10). Let me try moving west again - there might have been a monster in the way.
nh.move(direction="W")
```

**T59** · floor 1 · (59,10) · hp 250

```python
# I'm at (59,10). I need to reach '>' at (50,2). 
# I need to go north through the corridor. Let me check neighbors.
print(nh.map.neighbors())
```

**T60** · floor 1 · (58,9) · hp 250

```python
# I'm at (59,10). The '>' is at (50,2). I need to go NW through the corridor.
# Let me go NW to (58,9) which is floor, heading toward the upper rooms.
nh.move(direction="NW")
```

**T61** · floor 1 · (54,9) · hp 250

```python
# I'm at (58,9). I'm inside a room now. I need to go west through this room to reach '>' at (50,2).
# The room spans from about (52,9) to (60,9). I need to get through the '#' door at (52,10).
# Let me go west through this room.
nh.move(direction="W")
```

**T62** · floor 1 · (54,9) · hp 250

```python
# I'm at (54,9). There's a 'd' (dog) to my east at (56,9). 
# I need to go west through this room and then north to reach '>' at (50,2).
# The '#' door at (52,9) leads to the corridor going north.
# Let me check the map: row 9 shows #|@...d.|  - the wall is at (52,9).
# I need to go north from here. Let me check neighbors.
print(nh.map.neighbors())
```

**T63** · floor 1 · (54,14) · hp 250

```python
# I see a closed door at (53,10) to my SW. Let me go through it - it connects to the corridor going south/west.
# First, let me go south to (54,10) then through the door.
nh.move(direction="S")
```

**T64** · floor 1 · (54,9) · hp 250

```python
# I'm at (54,14) now - moved through the door into the lower room.
# I need to get to '>' at (50,2). Let me try move_to to navigate there.
nh.move_to(50, 2)
```

**T65** · floor 1 · (54,9) · hp 250

```python
# I'm at (54,9). The '>' is at (50,2). I need to go through the '+' door at (52,10).
# Let me go SW to reach the door.
nh.move(direction="SW")
```

**T66** · floor 1 · (54,14) · hp 250

```python
# I can't move diagonally into the door. The door is at (53,10) - SW of me.
# I need to go S first to (54,10), then W to (53,10) the door.
nh.move(direction="S")
```

**T67** · floor 1 · (53,14) · hp 250

```python
# I went through the door to (54,14). Now I need to get to '>' at (50,2).
# Let me try autoexplore to find the path there.
nh.autoexplore()
```

**T68** · floor 1 · (54,14) · hp 250

```python
# I'm at (53,14) in the bottom room. I need to get to '>' at (50,2) in the upper-right room.
# Looking at the map, the path goes: from this room, through the '#' corridors northward, 
# through the middle rooms, and up to the '>' room.
# 
# Let me trace the path:
# The '>' room is at rows 1-4, columns 37-53 (the rightmost top room).
# It has a '+' door at (38,2) and '#' corridors connecting it.
# 
# From row 14, I need to go north through the corridors.
# There's a corridor going north at around column 44-45.
# 
# Let me try moving to (45,13) which should be a corridor heading north.
nh.move(direction="E")
```

**T69** · floor 1 · (43,14) · hp 250

```python
# I'm at (54,14). Looking at row 14: the ########## corridor is to my west (columns 43-52).
# I need to go west through this corridor to reach the central area, then go north.
# Let me go west.
nh.move(direction="W")
```

**T70** · floor 1 · (43,13) · hp 250

```python
# I'm at (43,14). I moved west through the corridor. Now I need to go north.
# Looking at the map, there's a corridor going north from here. The '#' corridor at column 43 goes up.
# Let me go north.
nh.move(direction="N")
```


## ▼ DoD 2 — where it LOOPS  (turn 71, dlvl 2)

```
You hear someone cursing shoplifters.


                                 #            #
    -------------             -----      ------------              -----------
    |...........|             |...|  ####-..........|              |.......m.|
    |...........|             |....###   |.{........|             #-@........|
    |............#           #+...|      |y.........|             #-----------
    |...........|#           #|.Z.|     #+..........|             #
    ---------.---#           #|....#### #|..........|             ##
             #   #         ###---|-     #-------.----              #
             #   #         #   # ##     ####    ###                #
             #   #         #      ###      #  #####                #
        ######   ##------  #  -------------#  #---.-               #
  #######         #|....|  #  |...........+#  #|...|               #    ----
 -.------         #+....| ##  |...........| ###|...|       --------#    |..|
 |......|         #|>.... #   |...........+##  |*.$|       |.......#    |..|
 |.......##########------     -------------    |.@.-###    |......|     ----
 |......|              #                       -----  ##   |......|
 --------                                              ####.......|
                                                           --------
```

_The `>` down-stair is on this map and stays visible the whole time. Watch the model see it, start toward it, hit a wall, and restart — for 229 turns._

**T71** · floor 2 · (49,16) · hp 250 🔽 **DESCENT**

```python
# I'm at (43,13). I need to continue north through the corridor to reach '>' at (50,2).
# Looking at the map, the corridor goes north to row 12, then connects west/east.
# Let me try move_to(50,2) now that I'm in the corridor system.
nh.move_to(50, 2)
```

**T89** · floor 2 · (44,15) · hp 250

```python
# I'm at (45,14). The '>' is at (20,15). I need to keep going west.
# Looking at the map, I need to go west through the corridor system.
# From row 14: " -.------         #+....| ##  |...........| #@#|...|"
# I'm at position 45 in row 14. I need to go west.
# Let me continue with move_to.
nh.move_to(20, 15)
```

**T107** · floor 2 · (31,13) · hp 250

```python
# I'm at (31,15). West is wall. I need to go north to (31,14) then find a way west.
# Looking at the map, row 14: " -.------         #+....| ##  |...........| ###|...|"
# Position 31 in row 14 is '|' (wall). But neighbors say (31,14) is floor.
# Actually the map shows '.' at row 14. Let me go north first.
# Actually wait - looking more carefully at row 15: " |......|         #|>.... #   |@..^.......-##"
# I'm at position 31 which is '@'. The '#' at position 30 is a wall apparently.
# But there's a room at positions 9-25 in rows 15-17 with '>'.
# The room's east wall is at position 25 ('|'). 
# The corridor connecting to the '>' room goes through row 16: " |.......##########------"
# The ########## is at positions 10-19 connecting the '>' room to the wider corridor.
# I need to go north from (31,15) to (31,14), then west to find the corridor going down.
# Let me go north.
nh.move(direction="N")
```

**T125** · floor 2 · (43,10) · hp 250

```python
# I'm at (43,10) in the corridor. I moved north several steps.
# Now I need to go west through the corridor to reach the '>' room.
# Let me check what's to my west.
print(nh.map.neighbors())
```

**T143** · floor 2 · (33,15) · hp 250

```python
# I'm at (31,15). West is wall, south is wall. I can only go N, NE, or E.
# The '>' is at (20,15) to my west but wall blocks me.
# 
# Looking at the map, row 16: " |.......######e###------     -------------"
# The '######e####' corridor at row 16 connects the '>' room (left) to the right area.
# But south of me is wall. I need to go east, then south through the '-' door at (42,15),
# then west through the row 16 corridor.
# 
# Wait, row 15: " |......|         #|>.... #   |@..^.......-##"
# The '-' at (42,15) is a door. Let me go east to reach it, then south through the corridor.
# Actually, the '##' at (43,15)-(44,15) connects to the corridor going south.
# 
# Let me go east toward the door/corridor.
nh.move(direction="E")
```

**T161** · floor 2 · (43,10) · hp 250

```python
# I'm at (43,13). I need to go north through the corridor to reach the upper corridors
# that lead to (17,12) -> (18,13) -> (18,14) -> (19,14) door -> '>' at (20,15).
# Let me go north.
nh.move(direction="N")
```

**T179** · floor 2 · (43,10) · hp 250

```python
# North is wall. Let me check neighbors at (43,10).
print(nh.map.neighbors())
```

**T197** · floor 2 · (40,7) · hp 250

```python
# Let me check the corridor path from (40,10) southward and find connection to (18,14)
# I need to check the vertical corridors

# From (40,10), check south
for y in range(10, 20):
    print(f"(40,{y}):", nh.map.what_is(40, y))
    print(f"(43,{y}):", nh.map.what_is(43, y))

# Check the connection from (43,10) going south
print("\n--- Vertical corridor at x=43 ---")
for y in range(9, 16):
    print(f"(43,{y}):", nh.map.what_is(43, y))
```

**T215** · floor 2 · (40,8) · hp 211

```python
# I'm at (40,7). I need to go south through the corridor to reach the lower rooms.
# Let me go south to (40,8) then (40,9) then (40,10).
nh.move(direction="S")
```

**T233** · floor 2 · (40,8) · hp 224

```python
# I'm at (40,8). I need to reach (38,8) corridor but (39,8) is unseen rock.
# Let me search for hidden doors at this position.
nh.search(times=20)
```

**T251** · floor 2 · (35,13) · hp 247

```python
# I'm at (35,15). I moved west through the room. I can see '>' at (20,15) and 'B' at (22,15).
# There's a trap '^' at (34,15) to my west. The wall at (31,15) blocks direct path to '>'.
# 
# I need to go north to (31,13-14) area and search for secret doors in the west wall.
# Let me go north first.
nh.move(direction="N")
```

**T269** · floor 2 · (31,13) · hp 249

```python
# Kicking the wall hurt me. Let me try a different approach entirely.
# I notice the "'" at (22,14) in the map: "  -.------        ##-..'.| ##"
# And "'" at (21,13): "# #|B.r.|  #"
# 
# Wait - looking at row 14: " -.------        ##-..'.| ##  |...........| ###|...|"
# Position 22 = "'" - is this an open door or a golem?
# And row 13: "  #######       # #|B.r.|  #  |@..........-#"
# Position 20='B', 21='.', 22='r', 23='.'
# 
# The "'" at (22,14) in row 14: Let me check.
print("(22,14):", nh.map.what_is(22, 14))
print("(21,14):", nh.map.what_is(21, 14))
print("(23,14):", nh.map.what_is(23, 14))

# Actually, looking at the map row 14: " -.------        ##-..'.| ##"
# Let me count: 0=' ', 1='-', 2='.', 3-8='------', 9-15='        ', 
# 16='#', 17='#', 18='-', 19='.', 20='.', 21="'", 22='.', 23='|'
# 
# So "'" is at (21,14), not (22,14). Let me check.
print("\n(21,14) is:", nh.map.what_is(21, 14))
```

**T287** · floor 2 · (33,9) · hp 240

```python
# I'm being shot at! I need to move quickly toward the '>' stairs.
# I'm at (33,9). I see "'" (gold golem) at (24,15) and '>' at (20,15).
# Let me keep moving toward (18,14) -> (19,14) door -> (20,15) '>'.
nh.move_to(18, 14)
```


---
## What would fix it (and why we haven't just done it)

- The obvious fix — *"when stuck, path the agent toward the `>` it can see"* — is exactly the **locating crutch the experiment forbids**. Doing it turns the agent back into a find→go→descend bot and voids the result. (We tried philosophy-safe unsticks — undirected `autoexplore` — and they *hurt*, because they walk the agent *away* from the stair.)

- The honest levers are: **more independent tries per seed** (best-of-N — some tries won't hit the loop), or **a stronger policy model** that plans multi-step paths without looping. The base rate is ~23% floor-4 per game, so best-of-10 is the current bet.
