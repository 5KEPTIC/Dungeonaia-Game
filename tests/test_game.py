from dungeon.game import Position, Tile, generate_map, legal_moves, move_player, new_game, reachable_floor_tiles, visible_tiles

def test_seeded_maps_are_identical() -> None:
    first, start_first = generate_map(42)
    second, start_second = generate_map(42)
    assert first == second and start_first == start_second

def test_generated_rooms_are_connected() -> None:
    dungeon_map, start = generate_map(7)
    reachable = reachable_floor_tiles(dungeon_map, start)
    walkable = {Position(x, y) for y, row in enumerate(dungeon_map) for x, tile in enumerate(row) if tile != Tile.WALL}
    assert reachable == walkable

def test_walls_block_and_floors_allow_movement() -> None:
    state = new_game(3)
    start, blocked = next(
        (Position(x, y), delta)
        for y, row in enumerate(state.map)
        for x, tile in enumerate(row)
        if tile != Tile.WALL
        for delta in ((0, -1), (1, 0), (0, 1), (-1, 0))
        if 0 <= y + delta[1] < len(state.map)
        and 0 <= x + delta[0] < len(state.map[0])
        and state.map[y + delta[1]][x + delta[0]] == Tile.WALL
    )
    state.player.position = start
    assert move_player(state, *blocked) is False and state.player.position == start
    floor_delta = next(iter(legal_moves(state)))
    assert move_player(state, *floor_delta) is True and state.turn == 1

def test_new_game_tracks_field_of_view_and_exploration() -> None:
    state = new_game(9)
    assert state.visible == visible_tiles(state)
    assert state.visible <= state.explored
    assert state.player.position in state.visible
