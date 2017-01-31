###
# Limnoria plugin to retrieve statistics from NBA.com using their
# (undocumented) JSON API.
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

import supybot.utils as utils
from supybot.commands import *
import supybot.plugins as plugins
import supybot.ircutils as ircutils
import supybot.callbacks as callbacks
try:
    from supybot.i18n import PluginInternationalization
    _ = PluginInternationalization('NBAStats')
except ImportError:
    # Placeholder that allows to run the plugin on a bot
    # without the i18n module
    _ = lambda x: x

from . import nbastats

class NBAStats(callbacks.Plugin):
    """Get stats from NBA.com"""
    threaded = True

    def __init__(self, irc):
        self.__parent = super(NBAStats, self)
        self.__parent.__init__(irc)

        self._stats_getter = nbastats.NBAStatsGetter()

############################
# Public commands
############################
    def teamLeaders(self, irc, msg, args, team):
        """<TTT> (team tri-code)

        Get the team's current leaders."""
        team = team.upper()
        if not self._isTriCodeValid(team):
            irc.error("I could not find a team with that code")
            return

        team_leaders = self._stats_getter.teamLeaders(team)
        title = self._bold("{} Leaders ~ ".format(team))

        irc.reply("{} {}".format(title,
                                 self._teamLeadersToString(team_leaders)))

    leaders = wrap(teamLeaders, [('text').upper()])

    def teamRecord(self, irc, msg, args, team):
        """<TTT> (team tri-code)

        Get the team's record for this season."""
        team = team.upper()
        if not self._isTriCodeValid(team):
            irc.error("I could not find a team with that code")
            return

        team_record = self._stats_getter.teamRecord(team)

        title = "{} ~".format(team)
        irc.reply("{} {}".format(self._bold(title),
                                 self._teamRecordToString(team_record)))

    record = wrap(teamRecord, [('text')])

    def gameLeaders(self, irc, msg, args, team):
        """<TTT> (team tri-code)

        Get the game leaders for a team that has a game in progress."""
        team = team.upper()
        if not self._isTriCodeValid(team):
            irc.error("I could not find a team with that code")
            return

        if not self._stats_getter.isTeamPlaying(team):
            irc.error("{} is not currently playing".format(team))
            return

        leaders = self._stats_getter.gameLeaders(team)

        home_team_name = self._orange(leaders['home']['team_name'])
        away_team_name = self._blue(leaders['away']['team_name'])

        final_flag = ircutils.mircColor('(Final) ', 'red') \
                     if leaders['final'] else ""

        title = self._bold("{} @ {} Leaders {}~  ".format(away_team_name,
                                                          home_team_name,
                                                          final_flag))

        leaders_string = self._printableTeamLeaders(leaders)

        irc.reply(title + leaders_string)

    gameleaders = wrap(gameLeaders, [('text')])

    def standings(self, irc, msg, args, category):
        """[<conference/division>]

        Get standings for a given conference or division.
        If none is given, return standings for east and west."""

        conference = category.lower() if category is not None else category

        # No argument or argument is a conference:
        if conference is None or conference in ['east', 'west']:
            standings = self._stats_getter.conferenceStandings()

            display_west = conference is None or conference == 'west'
            display_east = conference is None or conference == 'east'

            if display_west:
                standings_west = self._printableStandings(standings['west'])
                irc.reply('{}: {}'.format(self._bold('WEST'), standings_west))
            if display_east:
                standings_east = self._printableStandings(standings['east'])
                irc.reply('{}: {}'.format(self._bold('EAST'), standings_east))
            return

        # Argument is a division:
        division = category.lower()
        if division not in self._stats_getter.divisions():
            valid_arguments = ', '.join(self._stats_getter.conferences() +
                                        self._stats_getter.divisions())
            irc.error('I could not find that conference or division. '
                      'Valid values are: {}.'.format(valid_arguments))
            return

        division_standings = self._stats_getter.divisionStandings(division)
        irc.reply('{}: {}'.format(self._bold(division.upper()),
                                  self._printableStandings(division_standings)))

    standings = wrap(standings, [optional('text')])

############################
############################
    def _isTriCodeValid(self, ttt):
        return (ttt.upper() in self._stats_getter.teams())

    def _isDivisionValid(self, division):
        return (division.lower() in self._stats_getter.divisions())


############################
# Formatting helpers
############################
    def _teamRecordToString(self, record):
        """Given the JSON entry for a team record, extract the relevant
        information, pertaining to the team's record, and return it in a
        printable form."""
        total = self._formatWinsLosses(record['total'])
        home = self._formatWinsLosses(record['home'])
        away = self._formatWinsLosses(record['away'])
        last_ten = self._formatWinsLosses(record['last_ten'])
        games_behind = record['games_behind']
        win_percentage = record['win_percentage']
        conference_rank = self._formatConferenceRank(record['conference_rank'])
        division_rank = self._formatDivisionRank(record['division_rank'])

        streak = self._formatStreak(record['streak'][0], record['streak'][1])

        return ('{} ({}) | {:g} GB | {} Conf. | {} Div. | {} Home | {} Away | '
                '{} Last 10 | {} Streak'.format(self._bold(total),
                                                win_percentage,
                                                games_behind,
                                                conference_rank, division_rank,
                                                home, away,
                                                last_ten, streak))

    def _teamLeadersToString(self, team_leaders):
        leaders = []
        for (category, name_tuple, value) in team_leaders:
            player_name = self._playerShortName(name_tuple)
            stat = self._printableStat(category, value)

            leaders.append("{} {}".format(player_name, stat))
        return " | ".join(leaders)

    def _printableTeamLeaders(self, leaders):
        """Given the JSON entry from the Scoreboard, extract the game leaders
        for each team and return them in a printable form."""
        home_team_name = self._highlightHomeTeam(leaders['home']['team_name'])
        away_team_name = self._highlightAwayTeam(leaders['away']['team_name'])

        home_leaders = self._gameLeadersToString(leaders['home']['leaders'],
                                                 home=True)
        away_leaders = self._gameLeadersToString(leaders['away']['leaders'],
                                                 home=False)

        return "{}: {} | {}: {}".format(self._bold(away_team_name),
                                        away_leaders,
                                        self._bold(home_team_name),
                                        home_leaders)

    def _gameLeadersToString(self, leaders, home):
        """Given a list of triples containing a type of stat., a list of player
        ids and a value, return the information in a printable form."""
        stats = []
        for (field, players, value) in leaders:
            field_name = self._shortCategoryName(field)
            player_list = ", ".join([self._playerShortName(p) \
                                     for p in players])
            stat_value = "{} {}".format(value, field_name)
            stat_string = self._highlightHomeTeam(stat_value) if home \
                          else self._highlightAwayTeam(stat_value)

            stats.append("{} {}".format(player_list, stat_string))

        return " | ".join(stats)

    def _printableStandings(self, standings):
        items = []
        for team in standings:
            team_name = self._bold(team['name'])
            games_behind_string = self._formatGamesBehind(-1*team['games_behind'])

            item = '{}.{} ({})'.format(team['rank'], team_name, games_behind_string)
            items.append(item)

        return ', '.join(items)

    def _printableStat(self, category, value):
        """Given a category identifier, and a corresponding value for it,
        return the printable format of type and value of the stat."""
        if category in ['fgp', 'ftp', 'tpp']:
            return self._blue("{} {}".format(self._decimalToPercentage(value),
                                              category.upper()))

        res = "{} {}".format(value, category.upper())

        if category in ['ppg', 'trpg', 'apg']:
            return self._green(res)

        if category in ['bpg', 'spg']:
            return self._purple(res)

        if category in ['tpg', 'pfpg']:
            return self._red(res)

        return self._orange(res)

    def _shortCategoryName(self, category):
        if category == 'rebounds':
            return 'REB'
        elif category ==  'points':
            return 'PTS'
        elif category == 'assists':
            return 'AST'
        return ""

    def _playerShortName(self, name_tuple):
        """ Given a tuple (FirstName, LastName), return 'I. LastName', where
        'I' is the first name initial."""
        first_name = name_tuple[0]
        last_name = name_tuple[1]
        initial = first_name[0]
        return "{}. {}".format(initial, last_name)

    def _formatWinsLosses(self, wins_losses_tuple):
        """Converts a tuple (wins, losses) into a color-coded 'wins-losses'
        string."""
        w = wins_losses_tuple[0]
        l = wins_losses_tuple[1]
        s = "{}-{}".format(w, l)

        if w > l:
            return self._green(s)
        elif l > w:
            return self._red(s)
        return self._yellow(s)

    def _formatStreak(self, streak, is_win):
        """Return the WX/LY streak representation color coded."""
        if streak == 0:
            return ""
        if is_win:
            return self._green("W{}".format(streak))
        else:
            return self._red("L{}".format(streak))

    def _formatConferenceRank(self, rank):
        """Return the rank ordinal. If the team is 8th or better (in playoffs),
        format it  green. Otherwise, red."""
        rank_string = self._numberToOrdinal(rank)
        if rank <= 8: # In the playoffs!
            return self._green(rank_string)
        return self._red(rank_string)

    def _formatConferenceRankBold(self, rank):
        if rank <= 8:
            return self._bold(rank)
        return rank

    def _formatDivisionRank(self, rank):
        return self._numberToOrdinal(rank)

    def _formatGamesBehind(self, games_behind):
        if abs(games_behind) > 0:
            return '{:>4}'.format(games_behind)
        return '--'

    def _numberToOrdinal(self, number):
        """Return the ordinal representation of the number. Only works for
        n <= 19."""
        if number > 19:
            return "{}".format(number)

        suffixes = ["th", "st", "nd", "rd", ] + ["th"] * 16
        suffixed_num = str(number) + suffixes[number % 100]
        return suffixed_num

    def _decimalToPercentage(self, p):
        return "{:.1f}%".format(float(p) * 100)


############################
# Coloring helpers
############################
    def _highlightHomeTeam(self, s):
        return self._orange(s)

    def _highlightAwayTeam(self, s):
        return self._blue(s)


############################
# IRC Colors
############################
    def _bold(self, s):
        return ircutils.bold(s)

    def _red(self, s):
        return ircutils.mircColor(s, 'red')

    def _green(self, s):
        return ircutils.mircColor(s, 'green')

    def _blue(self, s):
        return ircutils.mircColor(s, 'light blue', 'black')

    def _orange(self, s):
        return ircutils.mircColor(s, 'orange')

    def _yellow(self, s):
        return ircutils.mircColor(s, 'yellow', 'black')

    def _purple(self, s):
        return ircutils.mircColor(s, 'purple')

############################
############################

Class = NBAStats


# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:
