#!/usr/bin/env python3
###
# Python module to retrieve statistics from NBA.com using their (undocumented)
# JSON API.
# Copyright (c) 2016, Santiago Gil
#
#   This program is free software: you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program.  If not, see <http://www.gnu.org/licenses/>.
###

import cachecontrol
from cachecontrol import CacheControlAdapter
from cachecontrol.heuristics import LastModified

from collections import namedtuple
PlayerName  = namedtuple('PlayerName', 'first_name, last_name')
Record      = namedtuple('Record', 'wins, loses')
Streak      = namedtuple('Streak', 'games, is_winning')

PlayerStatistic = namedtuple('PlayerStatistic', 'category, player_name, value')
LeaderStatistic = namedtuple('LeaderStatistic', 'category, players, value')

import json
import requests

class NBAStatsGetter():
    """Get stats from NBA.com's JSON API."""
    def __init__(self):
        self._API_SERVER = "https://data.nba.net"

        self._cache_control_adapter = CacheControlAdapter(heuristic=LastModified())
        self._requests_session = requests.Session()
        self._requests_session.mount('http://', CacheControlAdapter())
        self._requests_session.mount('https://', CacheControlAdapter())

        self._TEAM_TRICODES = frozenset(('CHA', 'ATL', 'IND', 'MEM', 'DET',
                                         'UTA', 'CHI', 'TOR', 'CLE', 'OKC',
                                         'DAL', 'MIN', 'BOS', 'SAS', 'MIA',
                                         'DEN', 'LAL', 'PHX', 'NOP', 'MIL',
                                         'HOU', 'NYK', 'ORL', 'SAC', 'PHI',
                                         'BKN', 'POR', 'GSW', 'LAC', 'WAS'))

        self._STAT_CATEGORIES = frozenset(('ppg', 'trpg', 'apg', 'fgp', 'ftp',
                                           'tpp', 'bpg', 'spg', 'tpg', 'pfpg'))

        self._CONFERENCES = frozenset(('west', 'east'))

        self._EASTERN_DIVISIONS = frozenset(('southeast', 'atlantic', 'central'))
        self._WESTERN_DIVISIONS = frozenset(('southwest', 'pacific', 'northwest'))
        self._DIVISIONS = {'west': self._WESTERN_DIVISIONS,
                           'east': self._EASTERN_DIVISIONS}

        # Cached dictionaries. Saving these copies avoids having to
        # re-parse JSONs when they are returned from the HTTP cache.
        self._person_ids = None
        self._team_ids_to_tricodes = None
        self._team_tricodes_to_ids = None

############################
############################
    def teams(self):
        return self._TEAM_TRICODES

    def statCategories(self):
        return self._STAT_CATEGORIES

    def divisions(self, conference=None):
        if conference is None:
            return self._WESTERN_DIVISIONS | self._EASTERN_DIVISIONS
        if conference.lower() == 'west':
            return self._WESTERN_DIVISIONS
        if conference.lower() == 'east':
            return self._EASTERN_DIVISIONS

        raise ValueError("Invalid conference")

    def conferences(self):
        return self._CONFERENCES

    def teamLeaders(self, team):
        """Return a list with tuples (stat. category, player_id,
        value of the stat) representing the current team leaders
        for each stat category."""
        team = self._parseTeamTricode(team)

        team_id = self._teamID(team)
        leaders_json = self._fetchTeamLeaders(team_id)

        return self._extractTeamLeaders(leaders_json)

    def teamRecord(self, team):
        """Get the team's current record information for this season."""
        if not self._isTriCodeValid(team):
            raise ValueError("Invalid team value")

        team_id = self._teamID(team)
        team_standings_entry = self._fetchTeamStandingsEntry(team_id)

        return self._extractTeamRecord(team_standings_entry)

    def gameLeaders(self, team):
        """Get the game leaders for a team that has a game in progress."""
        team = self._parseTeamTricode(team)

        team_id = self._teamID(team)
        game = self._findGameInProgress(team_id)

        if game is None:
            raise ValueError("{} is not currently playing".format(team))

        box_score = self._fetchGameBoxScore(game['start_date'], game['game_id'])
        leaders = self._extractLeadersFromBoxScore(box_score)

        leaders['final'] = game['ended']

        return leaders

    def gameTextNugget(self, team):
        """Find the 'text nugget' (a string containing the description of a
        highlight of the game) for a game that involves the given team."""
        team = team.upper()
        self._validateTeamTricode(team)

        team_id = self._teamID(team)
        game = self._findGameInProgress(team_id)

        if game is None:
            raise ValueError("{} is not currently playing".format(team))

        return game['text_nugget']

    def conferenceStandings(self):
        """Find and return the standings for each conference.
        Returns a list of dictionaries in ranking order."""
        standings_json = self._getJSON(self._conferenceStandingsURL())
        return self._extractConferenceStandings(standings_json)

    def divisionStandings(self, division_filter=None):
        """Find and return the standings for each conference.
        Returns a list of dictionaries in ranking order."""
        standings_json = self._getJSON(self._divisionStandingsURL())
        standings = self._extractDivisionStandings(standings_json)

        if division_filter is None:
            return standings

        for conference in standings:
            for division in standings[conference]:
                if division_filter == division:
                    return standings[conference][division]
        raise ValueError("Invalid division")

    def _parseTeamTricode(self, team):
        """If the given string is a valid team tricode, normalize
        it to upper case. Otherwise throw a ValueError exception."""
        t = team.upper()
        if not self._isTriCodeValid(t):
            raise ValueError("Invalid team value")
        else:
            return t

    def _extractLeadersFromBoxScore(self, json):
        game_data = json['basicGameData']
        stats = json['stats']

        leaders = dict()
        leaders['home'] = dict()
        leaders['away'] = dict()

        away_team_name = game_data['vTeam']['triCode']
        home_team_name = game_data['hTeam']['triCode']
        leaders['home']['team_name'] = home_team_name
        leaders['away']['team_name'] = away_team_name

        home_leaders = self._extractGameLeadersStats(stats['hTeam']['leaders'])
        away_leaders = self._extractGameLeadersStats(stats['vTeam']['leaders'])

        leaders['home']['leaders'] = home_leaders
        leaders['away']['leaders'] = away_leaders

        return leaders

    def _extractGameLeadersStats(self, json):
        leaders = []
        for category in ['points', 'rebounds', 'assists']:
            category_leaders = [self.playerFullName(p['personId'])
                                for p in json[category]['players']]
            category_value = json[category]['value']

            leaders.append(LeaderStatistic(category,
                                           category_leaders,
                                           category_value))

        return leaders

    def _extractTeamRecord(self, e):
        """Extract the relevant fields from a team's Standings JSON entry."""
        team_record = dict()
        team_record['total'] = Record(int(e['win']), int(e['loss']))
        team_record['home'] = Record(int(e['homeWin']), int(e['homeLoss']))
        team_record['away'] = Record(int(e['awayWin']), int(e['awayLoss']))
        team_record['last_ten'] = Record(int(e['lastTenWin']),
                                         int(e['lastTenLoss']))
        team_record['conference_rank'] = int(e['confRank'])
        team_record['division_rank'] = int(e['divRank'])
        team_record['streak'] = Streak(int(e['streak']), e['isWinStreak'])
        team_record['games_behind'] = float(e['gamesBehind'])
        team_record['win_percentage'] = float(e['winPct'])
        return team_record

    def _extractTeamLeaders(self, json):
        """Returns a list of PlayerStatistic tuples."""
        leaders = []

        # Dropping the extra fields:
        json = json['league']['standard']

        for category in self.statCategories():
            # Taking the first player only:
            field = json[category][0]

            value = field['value']
            person = field['personId']
            leaders.append(PlayerStatistic(category,
                                           self.playerFullName(person),
                                           value))

        return leaders

    def _findGameInProgress(self, team_id):
        """Search for a game with the team is currently playing."""
        games_in_progress = self._gamesInProgress()
        for game in games_in_progress:
            if (game['home_team_id'] == team_id
                or game['away_team_id'] == team_id):
                return game
        return None

    def isTeamPlaying(self, team):
        team_id = self._teamID(team)
        return (self._findGameInProgress(team_id) is not None)

    def _todayGames(self):
        """Returns the entries of the games scheduled for today."""
        url = self._scoreboardURL()
        json = self._getJSON(url)
        games = self._extractGamesFromScoreboard(json)
        return games

    def _gamesInProgress(self):
        return self._getGamesInProgress(self._todayGames())

    def _isTriCodeValid(self, ttt):
        return (ttt.upper() in self._TEAM_TRICODES)

    def _getGamesInProgress(self, games):
        return [g for g in games if self._isGameInProgress(g)]

    def _isGameInProgress(self, game):
        return (game['period']['current'] != 0)

    def _extractGamesFromScoreboard(self, json):
        """Extract all relevant fields from NBA.com's scoreboard.json
        and return a list of games."""
        games = []
        for g in json['games']:
            game_info = {'game_id': g['gameId'],
                         'home_team': g['hTeam']['triCode'],
                         'home_team_id': g['hTeam']['teamId'],
                         'away_team': g['vTeam']['triCode'],
                         'away_team_id': g['vTeam']['teamId'],
                         'start_date': g['startDateEastern'],
                         'period': g['period'],
                         'ended': (g['statusNum'] == 3),
                         'text_nugget': g['nugget']['text']
                        }
            games.append(game_info)
        return games

    def _extractConferenceStandings(self, json):
        """Extract the standings for each conference."""
        json = json['league']['standard']['conference']

        standings = dict()
        for conference in json:
            standings[conference] = []
            for team in json[conference]:
                team_standing = {'name': self._teamTricode(team['teamId']),
                                 'games_behind': float(team['gamesBehind']),
                                 'rank': int(team['confRank'])}
                standings[conference].append(team_standing)
        return standings

    def _extractDivisionStandings(self, json):
        """Extract the standings for divisions in each conference."""
        json = json['league']['standard']['conference']

        standings = dict()

        for conference in json:
            standings[conference] = dict()
            for division in json[conference]:
                standings[conference][division] = []
                for team in json[conference][division]:
                    team_standing = {'name': self._teamTricode(team['teamId']),
                                     'games_behind': float(team['divGamesBehind']),
                                     'rank': int(team['divRank'])}
                    standings[conference][division].append(team_standing)
        return standings


############################
# Conversion to/from IDs
############################
    def playerFullName(self, person_id):
        """Given a person ID, return the corresponding full name."""
        names = self._fetchPersonIDdict()
        return names[person_id]

    def _teamID(self, team_tricode):
        """Given a tricode, return the team id corresponding to that team."""
        team_ids = self._tricodeToTeamIDdict()
        return team_ids[team_tricode]

    def _teamTricode(self, team_id):
        """Given a team id, return the tricode corresponding to that team."""
        team_tricodes = self._teamIDtoTricodeDict()
        return team_tricodes[team_id]

    def _updateTeamDictionaries(self):
        """Fetch (TeamId -> Tricode) and (Tricode -> TeamId) dictionaries,
        but just if it is necessary (checks cache first)."""
        (json, from_cache) = self._getJSON(self._teamListURL(),
                                           return_cache_status=True)

        # We have a parsed valid copy, return that:
        if from_cache and self._team_tricodes_to_ids is not None and \
           self._team_ids_to_tricodes is not None:
            return self._team_tricodes_to_ids

        # (Re-)creating dictionaries from JSON:
        tricode_to_ids = dict()
        ids_to_tricodes = dict()

        for team in json['league']['standard']:
            if team['isNBAFranchise']:
                tricode_to_ids[team['tricode']] = team['teamId']
                ids_to_tricodes[team['teamId']] = team['tricode']

        self._team_tricodes_to_ids = tricode_to_ids
        self._team_ids_to_tricodes = ids_to_tricodes

    def _tricodeToTeamIDdict(self):
        """Return a dictionary containing teams'
        (tricode -> id) mappings."""
        self._updateTeamDictionaries()
        return self._team_tricodes_to_ids

    def _teamIDtoTricodeDict(self):
        """Return a dictionary containing teams'
        (id -> tricode) mappings."""
        self._updateTeamDictionaries()
        return self._team_ids_to_tricodes

    def _fetchPersonIDdict(self):
        """PersonID -> (FirstName, LastName)"""
        (json, from_cache) = self._getJSON(self._playerListURL(),
                                           return_cache_status=True)

        # We have an parsed valid copy, return that:
        if from_cache and self._person_ids is not None:
            return self._person_ids

        # (Re-)creating dictionary from JSON:
        person_ids = dict()
        for player in json['league']['standard']:
            person_ids[player['personId']] = PlayerName(player['firstName'],
                                                        player['lastName'])

        self._person_ids = person_ids
        return person_ids

############################
# API URLS
############################
    # Time critical:
    def _todayEntryPointURL(self):
        return self._addBaseURL("/15m/prod/v1/today.json")

    def _scoreboardURL(self):
        return self._addBaseURL(self._todayJSONLink('todayScoreboard'))

    # Non time-critical (cache for 15 minutes):
    def _playerListURL(self):
        path = self._15MinMaxAgeLink(self._todayJSONLink('leagueRosterPlayers'))
        return self._addBaseURL(path)

    def _teamListURL(self):
        path = self._15MinMaxAgeLink(self._todayJSONLink('teams'))
        return self._addBaseURL(path)

    def _teamLeadersURL(self, team_id):
        team_leaders_URL = self._todayJSONLink('teamLeaders')
        team_leaders_URL = self._doubleBracketToSingle(team_leaders_URL)
        team_leaders_URL = team_leaders_URL.format(teamUrlCode=team_id)
        path = self._15MinMaxAgeLink(team_leaders_URL)
        return self._addBaseURL(path)

    def _standingsURL(self):
        path = self._15MinMaxAgeLink(self._todayJSONLink('leagueUngroupedStandings'))
        return self._addBaseURL(path)

    def _scoreBoxURL(self, starting_date, game_id):
        json_path = self._15MinMaxAgeLink(self._todayJSONLink('boxscore'))
        json_path = self._doubleBracketToSingle(json_path)
        json_path = json_path.format(gameDate=starting_date, gameId=game_id)
        return self._addBaseURL(json_path)

    def _conferenceStandingsURL(self):
        path = self._15MinMaxAgeLink(self._todayJSONLink('leagueConfStandings'))
        return self._addBaseURL(path)

    def _divisionStandingsURL(self):
        path = self._15MinMaxAgeLink(self._todayJSONLink('leagueDivStandings'))
        return self._addBaseURL(path)


############################
# API entry point
############################
    def _todayJSON(self):
        return self._getJSON(self._todayEntryPointURL())

    def _todayAnchorDate(self):
        return self._todayJSON()['anchorDate']

############################
############################
    def _getJSON(self, url, return_cache_status=False):
        """Get the JSON content of a given URL. If the return_cache_status is
        set to True, returns a tuple: (cache_status, json content).
        Cache_status indicates whether the content was stored in the cache,
        and thus whether local copy of its interpretation is still valid."""
        user_agent = 'Mozilla/5.0 \
                      (X11; Ubuntu; Linux x86_64; rv:45.0) \
                      Gecko/20100101 Firefox/45.0'
        header = {'User-Agent': user_agent}

        r = self._requests_session.get(url, headers=header)
        json = r.json()

        if not r.from_cache:
            print(url, r.status_code)

        if return_cache_status:
            return (json, r.from_cache)
        return json

############################
############################
    def _fetchGameBoxScore(self, start_date, game_id):
        game_url = self._scoreBoxURL(start_date, game_id)
        json = self._getJSON(game_url)
        return json

    def _fetchTeamLeaders(self, team_id):
        url = self._teamLeadersURL(team_id)
        json = self._getJSON(url)
        return json

    def _fetchTeamStandingsEntry(self, team_id):
        """Return the entry describing a team standing's information for a
        given team id."""
        url = self._standingsURL()
        json = self._getJSON(url)['league']['standard']['teams']

        for team in json:
            if team['teamId'] == team_id:
                return team

############################
############################
    def _doubleBracketToSingle(self, string):
        s = string.replace('{{', '{')
        return s.replace('}}', '}')

    def _addBaseURL(self, path):
        return self._API_SERVER + path

    def _todayJSONLink(self, endpoint):
        return self._todayJSON()['links'][endpoint]

    def _15MinMaxAgeLink(self, link):
        return link.replace('10s', '15m')

def test():
    n = NBAStatsGetter()
    print('LAL record:', n.teamRecord('LAL'))
    print('-'*60)
    print('Standings:', n.conferenceStandings())
    print('-'*60)
    print('LAL leaders:', n.teamLeaders('LAL'))
    print('-'*60)
    print(n.gameLeaders('LAL'))

if __name__ == "__main__":
    test()