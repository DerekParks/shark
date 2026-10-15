from dateutil import parser

import merge


def game(name, start, end):
  return {"name": name, "start": parser.parse(start), "end": parser.parse(end)}


def collection(*games):
  return sorted(games, key=merge.gameStart)


def test_no_conflict_with_empty_schedule():
  assert merge.findConflict(collection(), game("a", "2017-04-02 18:00Z", "2017-04-02 21:00Z")) is None


def test_conflict_with_earlier_game_still_running():
  earlier = game("earlier", "2017-04-02 18:00Z", "2017-04-02 21:00Z")

  row = game("row", "2017-04-02 20:00Z", "2017-04-02 23:00Z")

  assert merge.findConflict(collection(earlier), row) is earlier


def test_conflict_with_later_game_starting_before_row_ends():
  later = game("later", "2017-04-02 20:00Z", "2017-04-02 23:00Z")

  row = game("row", "2017-04-02 18:00Z", "2017-04-02 21:00Z")

  assert merge.findConflict(collection(later), row) is later


def test_games_with_a_gap_do_not_conflict():
  earlier = game("earlier", "2017-04-02 12:00Z", "2017-04-02 15:00Z")
  later = game("later", "2017-04-03 00:00Z", "2017-04-03 03:00Z")

  row = game("row", "2017-04-02 18:00Z", "2017-04-02 21:00Z")

  assert merge.findConflict(collection(earlier, later), row) is None


def test_add_file_keeps_first_seen_game_on_conflict(tmpdir):
  csvFile = tmpdir.join("games.csv")
  csvFile.write("\n".join([
    "team,name,start,end,band,freq",
    "Nuggets,late,2017-04-02 20:00:00+00:00,2017-04-02 22:30:00+00:00,AM,950",
    "Rockies,early,2017-04-02 18:00:00+00:00,2017-04-02 21:00:00+00:00,FM,94.1",
  ]))
  games = collection()

  merge.addFile(str(csvFile), games)

  assert [g["name"] for g in games] == ["late"]
