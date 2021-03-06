#!/usr/bin/env python

# movetags.py
#
# movetags.py copyright (c) 2010-2013 Mark Henkelis
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# Author: Mark Henkelis <mark.henkelis@tesco.net>

import os
import sys
import sqlite3
import optparse
import re
import time
import codecs
import ConfigParser
import datetime
from collections import defaultdict
from dateutil.parser import parse as parsedate
from scanfuncs import adjust_tracknumber, truncate_number
import filelog

import errors
errors.catch_errors()

MULTI_SEPARATOR = '\n'
enc = sys.getfilesystemencoding()
DEFAULTYEAR = 1
DEFAULTMONTH = 1
DEFAULTDAY = 1
DEFAULTDATE = datetime.datetime(DEFAULTYEAR, DEFAULTMONTH, DEFAULTDAY)

def process_tags(args, options, tagdatabase, trackdatabase):

    # tag_update records are processed sequentially as selected by id
    # only records that have changed will have a tag_update pair
    # each pair of tag_update records relate to a track record
    # each track record can result in album/artist/albumartist/composer and genre records
    # each track record can also result in lookup records for each of album/artist/albumartist/composer/genre
    # each track record can also result in work/virtual/tracknumber records
    # lookup records are maintained to reduce DB access for library operation on small machines
    # DB size is not constrained as the library is expected to have sufficient disk available
    # artist/albumartist/composer/genre are multi entry fields, so can result in multiple lookup records
    # lookup records are unique
    # state is not maintained across tag_update/track records to save memory - the db is checked for duplicates on insert

    logstring = "Processing tags"
    filelog.write_log(logstring)
    
    db2 = sqlite3.connect(trackdatabase)
    db2.execute("PRAGMA synchronous = 0;")
    cs2 = db2.cursor()

    if tagdatabase == trackdatabase:
        db1 = sqlite3.connect(tagdatabase)
        cs1 = db1.cursor()
        cs1.execute("attach '' as tempdb")
        cs1.execute("""create table tempdb.tags_update as select * from tags_update""")
        cs1.execute("""create table tempdb.tags as select * from tags""")
        cs1.execute("""create table tempdb.workvirtuals_update as select * from workvirtuals_update""")
    else:
        db1 = sqlite3.connect(tagdatabase)
        cs1 = db1.cursor()

#    artist_parentid = 100000000
#    album_parentid = 300000000
#    composer_parentid = 400000000
#    genre_parentid = 500000000
#    track_parentid = 600000000
#    playlist_parentid = 700000000

    # get ini settings
    config = ConfigParser.ConfigParser()
    config.optionxform = str
    config.read('scan.ini')

    # 'the' processing
    # command line overrides ini
    if options.the_processing:
        the_processing = options.the_processing.lower()
        logstring = "'The' processing: %s" % the_processing
        filelog.write_verbose_log(logstring)
    else:
        the_processing = 'remove'
        try:        
            the_processing = config.get('movetags', 'the_processing')
            the_processing = the_processing.lower()
        except ConfigParser.NoSectionError:
            pass
        except ConfigParser.NoOptionError:
            pass

    # multi-field separator
    multi_field_separator = ''
    try:        
        multi_field_separator = config.get('movetags', 'multiple_tag_separator')
    except ConfigParser.NoSectionError:
        pass
    except ConfigParser.NoOptionError:
        pass

    # multi-field inclusions
    include_album = 'all'
    try:        
        include_album = config.get('movetags', 'include_album')
        include_album = include_album.lower()
    except ConfigParser.NoSectionError:
        pass
    except ConfigParser.NoOptionError:
        pass
    if not include_album in ['all', 'first', 'last']: include_album = 'all'

    include_artist = 'all'
    try:        
        include_artist = config.get('movetags', 'include_artist')
        include_artist = include_artist.lower()
    except ConfigParser.NoSectionError:
        pass
    except ConfigParser.NoOptionError:
        pass
    if not include_artist in ['all', 'first', 'last']: include_artist = 'all'

    include_albumartist = 'all'
    try:        
        include_albumartist = config.get('movetags', 'include_albumartist')
        include_albumartist = include_albumartist.lower()
    except ConfigParser.NoSectionError:
        pass
    except ConfigParser.NoOptionError:
        pass
    if not include_albumartist in ['all', 'first', 'last']: include_albumartist = 'all'
    
    include_composer = 'all'
    try:        
        include_composer = config.get('movetags', 'include_composer')
        include_composer = include_composer.lower()
    except ConfigParser.NoSectionError:
        pass
    except ConfigParser.NoOptionError:
        pass
    if not include_composer in ['all', 'first', 'last']: include_composer = 'all'
    
    include_genre = 'all'
    try:        
        include_genre = config.get('movetags', 'include_genre')
        include_genre = include_genre.lower()
    except ConfigParser.NoSectionError:
        pass
    except ConfigParser.NoOptionError:
        pass
    if not include_genre in ['all', 'first', 'last']: include_genre = 'all'

    # art preference
    prefer_folderart = False
    try:        
        prefer_folderart_option = config.get('movetags', 'prefer_folderart')
        if prefer_folderart_option.lower() == 'y':
            prefer_folderart = True
    except ConfigParser.NoSectionError:
        pass
    except ConfigParser.NoOptionError:
        pass

    # exception album titles
    separate_album_list = []
    try:        
        separate_albums = config.get('movetags', 'separate_album_list')
        separate_album_list = split_on_comma(separate_albums)
    except ConfigParser.NoSectionError:
        pass
    except ConfigParser.NoOptionError:
        pass

    # names
    lookup_name_dict = {}
    workvirtualvalues = {}
    workvirtualvalues['_ALBUM'] = 10

    work_name_structures = []
    try:        
        work_name_structures = config.items('work name format')
    except ConfigParser.NoSectionError:
        pass
    except ConfigParser.NoOptionError:
        pass
    workstructurelist = [('_DEFAULT_WORK', '"%s - %s - %s" % (composer, work, artist)', 200)]
    workvirtualvalues['_DEFAULT_WORK'] = 200
    work_number = 201
    for k,v in work_name_structures:
        if k[0] == '_':
            lookup_name_dict[k] = v
        else:
            workstructurelist += [(k, v, work_number)]
            workvirtualvalues[k] = work_number
            work_number += 1

    virtual_name_structures = []
    try:        
        virtual_name_structures = config.items('virtual name format')
    except ConfigParser.NoSectionError:
        pass
    except ConfigParser.NoOptionError:
        pass
    workvirtualvalues['_DEFAULT_VIRTUAL'] = 100
    virtualstructurelist = [('_DEFAULT_VIRTUAL', '"%s" % (virtual)', 100)]
    virtual_number = 101
    for k,v in virtual_name_structures:
        if k[0] == '_':
            lookup_name_dict[k] = v
        else:
            virtualstructurelist += [(k, v, virtual_number)]
            workvirtualvalues[k] = virtual_number
            virtual_number += 1
    # virtualstructurelist = [('_DEFAULT_VIRTUAL', '"%s" % (virtual)', 100), ('ALBUM_VIRTUAL', '"%s - %s" % (virtual, artist)', 101)]

    # convert user defined fields and create old and new structures
    old_structures_work, new_structures_work = convertstructure(workstructurelist, lookup_name_dict)
    old_structures_virtual, new_structures_virtual = convertstructure(virtualstructurelist, lookup_name_dict)

    # save workvirtual numbers to database
    try:
        for k, v in workvirtualvalues.iteritems():
            cs2.execute('insert into wvlookup values (?, ?)', (k, v))
    except sqlite3.Error, e:
        errorstring = "Error writing workvirtual numbers: %s" % e.args[0]
        filelog.write_error(errorstring)

    # get outstanding scan details
    db3 = sqlite3.connect(tagdatabase)
    cs3 = db3.cursor()
    try:
        cs3.execute("""select * from scans""")
    except sqlite3.Error, e:
        errorstring = "Error querying scan details: %s" % e.args[0]
        filelog.write_error(errorstring)

    #  buffer in memory
    scan_count = 0
    scan_details = []
    for srow in cs3:
        id, path = srow
        scan_details.append((id,path))
        scan_count += 1

    cs3.close()

    if options.scancount != None:
        logstring = "Scan count: %d" % options.scancount
        filelog.write_verbose_log(logstring)

    # process outstanding scans
    scan_count = 0
    last_scan_stamp = 0
    for scan_row in scan_details:

        scan_id, scan_path = scan_row
        scan_count += 1
        
        if options.scancount != None:   # need to be able to process zero
            if scan_count > options.scancount:
                break
        
        if not options.quiet and not options.verbose:
            out = ''
            if scan_count != 1: out += '\n'
            out += "Scannumber: %d\n" % scan_id
            sys.stderr.write(out)
            sys.stderr.flush()

        processing_count = 1

        try:

            albumsonlylist = []
            
            logstring = "Processing tags from scan: %d" % scan_id
            filelog.write_verbose_log(logstring)

            # process tag records that exist for this scan
            if tagdatabase != trackdatabase:
                select_tu = 'tags_update'
                select_wv = 'workvirtuals_update'
                select_t  = 'tags'
            else:
                select_tu = 'tempdb.tags_update'
                select_wv = 'tempdb.workvirtuals_update'
                select_t  = 'tempdb.tags'
            if options.regenerate:
                orderby_tu = 'id, updateorder'
                orderby_wv = 'w.wvfile, w.plfile, w.id, w.title, w.type, w.occurs, w.updateorder'
            else:
                orderby_tu = 'updatetype, rowid'
                orderby_wv = 'w.updatetype, w.rowid'

            # we need to process tags_updates followed by workvirtuals_updates
            # 1) for tags we just select from tags_updates
            # 2) to get the full data for workvirtuals inserts/updates we join with tags (not tags_updates as it
            #    doesn't contain all the records we need (remember tags is the after image too))
            # 3) to get the full data for workvirtuals deletes we join with tags or tags_updates (if tag
            #    records have been deleted)
            # Note 1:
            #    In the SQL if we are processing a wv delete and the track exists in tags, it will be found in
            #    the second select (but not the third as it won't exist in tags_update). If the track does not 
            #    exist in tags then it must have been deleted and will exist in tags_update, so will be found
            #    in the third select (but not the second).
            # Note 2:
            #    Because virtuals/works can contain the same track more than once, and the same track can be in
            #    multiple virtuals and/or works, we need to ensure we keep the correct record order in the select
            #    if regenerating (using virtual/work title, type and occurs)
            # Note 3:
            #    Because a user can have identical virtuals/works in separate files, we need to ensure we keep
            #    the correct record order in the select if regenerating (using wvfile and plfile). Note that only
            #    one will be picked up
            # Note 4:
            #    The SQL assumes that the final result will conform to the three separate order by clauses
            statement = '''
                        select * from (
                            select *, '', 'album', '', -1 from %s where scannumber=? order by %s
                        ) first

                        union all

                        select * from (
                            select t.id, t.id2,
                                    t.title, w.artist, w.title,
                                    w.genre, w.track, w.year,
                                    w.albumartist, w.composer, t.codec,
                                    t.length, t.size,
                                    w.created, t.path, t.filename,
                                    w.discnumber, t.comment, 
                                    t.folderart, t.trackart,
                                    t.bitrate, t.samplerate, 
                                    t.bitspersample, t.channels, t.mime,
                                    w.lastmodified,
                                    w.scannumber, t.folderartid, t.trackartid,
                                    w.inserted, w.lastscanned,
                                    w.titlesort, w.albumsort, w.artistsort, 
                                    w.albumartistsort, w.composersort,
                                    w.updateorder, w.updatetype,
                                    t.album, w.type,
                                    w.cover, w.coverartid
                            from %s w, %s t
                            on t.id = w.id
                            where w.scannumber=?
                            order by %s
                        ) second

                        union all

                        select * from (
                            select t.id, t.id2,
                                    t.title, w.artist, w.title,
                                    w.genre, w.track, w.year,
                                    w.albumartist, w.composer, t.codec,
                                    t.length, t.size,
                                    w.created, t.path, t.filename,
                                    w.discnumber, t.comment, 
                                    t.folderart, t.trackart,
                                    t.bitrate, t.samplerate, 
                                    t.bitspersample, t.channels, t.mime,
                                    w.lastmodified,
                                    w.scannumber, t.folderartid, t.trackartid,
                                    w.inserted, w.lastscanned,
                                    w.titlesort, w.albumsort, w.artistsort, 
                                    w.albumartistsort, w.composersort,
                                    w.updateorder, w.updatetype,
                                    t.album, w.type,
                                    w.cover, w.coverartid
                            from %s w inner join %s t
                            on t.id = w.id and t.updatetype = w.updatetype and t.updateorder = w.updateorder
                            where w.scannumber=?
                            and w.updatetype='D'
                            order by %s
                        ) third

                        ''' % (select_tu, orderby_tu, select_wv, select_t, orderby_wv, select_wv, select_tu, orderby_wv)
 
            cs1.execute(statement, (scan_id, scan_id, scan_id))

            for row0 in cs1:

                # get second record of pair
                row1 = cs1.fetchone()

                filelog.write_verbose_log(str(row0))
                filelog.write_verbose_log(str(row1))

                if not options.quiet and not options.verbose:
                    out = "    processing tag: " + str(processing_count) + "\r" 
                    sys.stderr.write(out)
                    sys.stderr.flush()
                    processing_count += 1

                o_id, o_id2, o_title, o_artistliststring, o_albumliststring, o_genreliststring, o_tracknumber, o_year, o_albumartistliststring, o_composerliststring, o_codec, o_length, o_size, o_created, o_path, o_filename, o_discnumber, o_commentliststring, o_folderart, o_trackart, o_bitrate, o_samplerate, o_bitspersample, o_channels, o_mime, o_lastmodified, o_scannumber, o_folderartid, o_trackartid, o_inserted, o_lastscanned, o_titlesort, o_albumsort, o_artistsort, o_albumartistsort, o_composersort, o_updateorder, o_updatetype, o_originalalbum, o_albumtypestring, o_coverart, o_coverartid = row0
                id, id2, title, artistliststring, albumliststring, genreliststring, tracknumber, year, albumartistliststring, composerliststring, codec, length, size, created, path, filename, discnumber, commentliststring, folderart, trackart, bitrate, samplerate, bitspersample, channels, mime, lastmodified, scannumber, folderartid, trackartid, inserted, lastscanned, titlesort, albumsort, artistsort, albumartistsort, composersort, updateorder, updatetype, originalalbum, albumtypestring, coverart, coverartid = row1
                o_filespec = os.path.join(o_path, o_filename)
                filespec = os.path.join(path, filename)

                # check that we do indeed have a pair
                if o_id != id:
                    # should only get here if we have a serious problem
                    errorstring = "tag/workvirtual update record pair does not match on ID"
                    filelog.write_error(errorstring)
                    continue
                if o_updateorder != 0 or updateorder != 1:
                    # should only get here if we have a serious problem
                    errorstring = "tag/workvirtual update record pair update order wrong"
                    filelog.write_error(errorstring)
                    print repr(row0)
                    print repr(row1)
                    continue

                # integerise dates (= second accuracy)
                o_created = makeint(o_created)
                o_lastmodified = makeint(o_lastmodified)
                o_inserted = makeint(o_inserted)
                o_lastscanned = makeint(o_lastscanned)
                created = makeint(created)
                lastmodified = makeint(lastmodified)
                inserted = makeint(inserted)
                lastscanned = makeint(lastscanned)

                # save latest scan time
                this_scan_stamp = lastscanned
                if this_scan_stamp > last_scan_stamp:
                    last_scan_stamp = this_scan_stamp

                # update type shows how to process
                # if 'I' is a new file
                # elif 'U' contains updates from an existing file
                # elif 'D' is a deleted file

                o_genrelist = []
                o_artistlist = []
                o_albumartistlist = []
                o_composerlist = []
                o_albumlist = []

                if updatetype == 'D' or updatetype == 'U':
                
                    # remove redundant separators
                    o_title = remove_sep(o_title)
                
                    # separate out multi-entry lists and perform 'the' processing
                    o_genreliststringfull, o_genreliststring, o_genrelist = unwrap_list(o_genreliststring, multi_field_separator, include_genre, 'no')
                    o_artistliststringfull, o_artistliststring, o_artistlist = unwrap_list(o_artistliststring, multi_field_separator, include_artist, the_processing)
                    o_albumartistliststringfull, o_albumartistliststring, o_albumartistlist = unwrap_list(o_albumartistliststring, multi_field_separator, include_albumartist, the_processing)
                    o_composerliststringfull, o_composerliststring, o_composerlist = unwrap_list(o_composerliststring, multi_field_separator, include_composer, the_processing)
                    o_albumliststringfull, o_albumliststring, o_albumlist = unwrap_list(o_albumliststring, multi_field_separator, include_album, 'no')

                    # TODO: allow for multiple sort entries
#                    o_titlesort
#                    o_albumsort
#                    o_artistsort
#                    o_albumartistsort
#                    o_composersort
                        
                    # adjust various fields
                    o_tracknumber = adjust_tracknumber(o_tracknumber)
                    o_year = adjust_year(o_year, o_filespec)
                    o_length = truncate_number(o_length)
                    o_size = truncate_number(o_size)
                    o_discnumber = truncate_number(o_discnumber)
                    o_bitrate = truncate_number(o_bitrate)
                    o_samplerate = truncate_number(o_samplerate)
                    o_bitspersample = truncate_number(o_bitspersample)
                    o_channels = truncate_number(o_channels)
                    o_folderartid = truncate_number(o_folderartid)
                    o_trackartid = truncate_number(o_trackartid)

                    # adjust albumartist - if there isn't one, copy in artist
                    if o_albumartistliststring == '':
                        o_albumartistliststringfull = o_artistliststringfull
                        o_albumartistliststring = o_artistliststring
                        o_albumartistlist = o_artistlist

                genrelist = []
                artistlist = []
                albumartistlist = []
                composerlist = []
                albumlist = []

                if updatetype == 'I' or updatetype == 'U':

                    # remove redundant separators
                    title = remove_sep(title)
                
                    # separate out multi-entry lists and perform the processing
                    genreliststringfull, genreliststring, genrelist = unwrap_list(genreliststring, multi_field_separator, include_genre, 'no')
                    artistliststringfull, artistliststring, artistlist = unwrap_list(artistliststring, multi_field_separator, include_artist, the_processing)
                    albumartistliststringfull, albumartistliststring, albumartistlist = unwrap_list(albumartistliststring, multi_field_separator, include_albumartist, the_processing)
                    composerliststringfull, composerliststring, composerlist = unwrap_list(composerliststring, multi_field_separator, include_composer, the_processing)
                    albumliststringfull, albumliststring, albumlist = unwrap_list(albumliststring, multi_field_separator, include_album, 'no')
                        
                    # adjust various fields
                    tracknumber = adjust_tracknumber(tracknumber)
                    year = adjust_year(year, filespec)
                    length = truncate_number(length)
                    size = truncate_number(size)
                    discnumber = truncate_number(discnumber)
                    bitrate = truncate_number(bitrate)
                    samplerate = truncate_number(samplerate)
                    bitspersample = truncate_number(bitspersample)
                    channels = truncate_number(channels)
                    folderartid = truncate_number(folderartid)
                    trackartid = truncate_number(trackartid)

                    # adjust albumartist - if there isn't one, copy in artist
                    if albumartistliststring == '':
                        albumartistliststringfull = artistliststringfull
                        albumartistliststring = artistliststring
                        albumartistlist = artistlist

                # process track

                # don't process track table if work or virtual                
                if albumtypestring != 'album':

                    # for work/virtual need track id
                    try:
                        cs2.execute("""select rowid, id, duplicate from tracks where path=? and filename=?""",
                                    (o_path, o_filename))
                        row = cs2.fetchone()
                        if row:
                            track_rowid, track_id, o_duplicate = row
                            # duplicate won't exist in new data for an update, so force it
                            duplicate = o_duplicate
                    except sqlite3.Error, e:
                        errorstring = "Error getting track id: %s" % e.args[0]
                        filelog.write_error(errorstring)

                else:

                    # for update/delete need track id
                    if updatetype == 'D' or updatetype == 'U':
                        try:
                            cs2.execute("""select rowid, id, duplicate from tracks where path=? and filename=?""",
                                        (o_path, o_filename))
                            row = cs2.fetchone()
                            if row:
                                track_rowid, track_id, o_duplicate = row
                                # duplicate won't exist in new data for an update, so force it
                                duplicate = o_duplicate
                        except sqlite3.Error, e:
                            errorstring = "Error getting track id: %s" % e.args[0]
                            filelog.write_error(errorstring)

                    if updatetype == 'D':
                        try:
                            logstring = "DELETE TRACK: %s" % str(row0)
                            filelog.write_verbose_log(logstring)
                            cs2.execute("""delete from tracks where id=?""", (track_id,))
                        except sqlite3.Error, e:
                            errorstring = "Error deleting track details: %s" % e.args[0]
                            filelog.write_error(errorstring)
                    
                    elif updatetype == 'I':
                    
                        # new track, so insert
                        duplicate = 0   # used if a track is duplicated, for both the track and the album
                        try:
                            tracks = (id, id2, duplicate, title, artistliststring, artistliststringfull, albumliststringfull, genreliststringfull, tracknumber, year, albumartistliststring, albumartistliststringfull, composerliststring, composerliststringfull, codec, length, size, created, path, filename, discnumber, commentliststring, folderart, trackart, bitrate, samplerate, bitspersample, channels, mime, lastmodified, folderartid, trackartid, inserted, '', '', lastscanned, titlesort, albumsort)
                            logstring = "INSERT TRACK: %s" % str(tracks)
                            filelog.write_verbose_log(logstring)
                            cs2.execute('insert into tracks values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', tracks)
                            track_rowid = cs2.lastrowid
                        except sqlite3.Error, e:
                            # assume we have a duplicate
                            # Sonos doesn't like duplicate names, so append a number and keep trying
                            
                            tstring = title + " (%"
                            try:
                                cs2.execute("""select max(duplicate) from tracks where title like ? and album=? and artist=? and tracknumber=?""",
                                            (tstring, albumliststringfull, artistliststring, tracknumber))
                                row = cs2.fetchone()
                            except sqlite3.Error, e:
                                errorstring = "Error finding max duplicate on track insert: %s" % e
                                filelog.write_error(errorstring)
                            if row:
                                tduplicate, = row
                                # special case for second entry - first won't have been matched
                                if not tduplicate:
                                    tcount = 2
                                else:
                                    tcount = int(tduplicate) + 1
                                tstring = title + " (" + str(tcount) + ")"            
                                tracks = (id, id2, tcount, tstring, artistliststring, artistliststringfull, albumliststringfull, genreliststringfull, tracknumber, year, albumartistliststring, albumartistliststringfull, composerliststring, composerliststringfull, codec, length, size, created, path, filename, discnumber, commentliststring, folderart, trackart, bitrate, samplerate, bitspersample, channels, mime, lastmodified, folderartid, trackartid, inserted, '', '', lastscanned, titlesort, albumsort)
                                logstring = "INSERT TRACK: %s" % str(tracks)
                                filelog.write_verbose_log(logstring)
                                try:
                                    cs2.execute('insert into tracks values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', tracks)
                                    track_rowid = cs2.lastrowid
                                    duplicate = tcount
                                except sqlite3.Error, e:
                                    errorstring = "Error performing duplicate processing on track insert: %s" % e
                                    filelog.write_error(errorstring)
                                    
    #                    track_id = cs2.lastrowid
                        track_id = id

                    elif updatetype == 'U':
                        
                        # existing track, so update track with changes
                        try:
                            # recreate title if duplicate
                            if o_duplicate != 0:
                                title = title + " (" + str(o_duplicate) + ")"            

                            tracks = (id2, title, artistliststring, artistliststringfull, albumliststringfull, genreliststringfull, tracknumber, year, albumartistliststring, albumartistliststringfull, composerliststring, composerliststringfull, codec, length, size, created, discnumber, commentliststring, folderart, trackart, bitrate, samplerate, bitspersample, channels, mime, lastmodified, folderartid, trackartid, inserted, lastscanned, titlesort, albumsort, track_id)
                            logstring = "UPDATE TRACK: %s" % str(tracks)
                            filelog.write_verbose_log(logstring)
                            cs2.execute("""update tracks set 
                                           id2=?, title=?, artist=?, artistfull=?, album=?, 
                                           genre=?, tracknumber=?, year=?, 
                                           albumartist=?, albumartistfull=?, composer=?, composerfull=?, codec=?, 
                                           length=?, size=?, 
                                           created=?, 
                                           discnumber=?, comment=?, 
                                           folderart=?, trackart=?,
                                           bitrate=?, samplerate=?, 
                                           bitspersample=?, channels=?, mime=?,
                                           lastmodified=?,
                                           folderartid=?, trackartid=?,
                                           inserted=?, lastscanned=?,
                                           titlesort=?, albumsort=? 
                                           where id=?""", 
                                           tracks)
                        except sqlite3.Error, e:
                            errorstring = "Error updating track details: %s" % e.args[0]
                            filelog.write_error(errorstring)

                # album

                # Note:
                #     work and virtual entries come in as separate rows
                #     there can be multiple work and virtual names per track
                
                # For normal albums we want to set the album details from the lowest track number.
                # Really we expect that to be 1, but it won't be if the album is incomplete
                # or the tracknumbers are blank.
                # We need to check tracks as they come in, storing details from successively lower
                # track numbers (only).
                # So that it is easier to reset album details from the next lowest track number
                # if the lowest is deleted, we store the track numbers we encounter and maintain
                # that list across deletes
                
                # For works and virtuals we use their tracknumber (which may be the original
                # tracknumber or a number set in the work/virtual data). We process those
                # tracknumbers as for albums
                
                albumentries = []
                structures = []
                
                o_worklist = worklist = o_virtuallist = virtuallist = ['']

                if updatetype != 'I':
                    if albumtypestring == 'album':
                        albumentries.append((o_tracknumber, o_albumliststringfull, workvirtualvalues['_ALBUM'], albumtypestring, 'old'))
                    elif albumtypestring == 'work':
                        structures.append((old_structures_work, o_tracknumber, 'old'))
                        o_worklist = o_albumlist
                    elif albumtypestring == 'virtual':
                        structures.append((old_structures_virtual, o_tracknumber, 'old'))
                        o_virtuallist = o_albumlist
                if updatetype != 'D':
                    if albumtypestring == 'album':
                        albumentries.append((tracknumber, albumliststringfull, workvirtualvalues['_ALBUM'], albumtypestring, 'new'))
                    elif albumtypestring == 'work':
                        structures.append((new_structures_work, tracknumber, 'new'))
                        worklist = albumlist
                    elif albumtypestring == 'virtual':
                        structures.append((new_structures_virtual, tracknumber, 'new'))
                        virtuallist = albumlist

                if albumtypestring != 'album':

                    # this is a work or a virtual

                    # create combinaton lists
                    o_artistlisttmp = o_artistlist if o_artistlist != [] else ['']
                    artistlisttmp = artistlist if artistlist != [] else ['']
                    o_albumartistlisttmp = o_albumartistlist if o_albumartistlist != [] else ['']
                    albumartistlisttmp = albumartistlist if albumartistlist != [] else ['']
                    o_composerlisttmp = o_composerlist if o_composerlist != [] else ['']
                    composerlisttmp = composerlist if composerlist != [] else ['']
                    o_genrelisttmp = o_genrelist if o_genrelist != [] else ['']
                    genrelisttmp = genrelist if genrelist != [] else ['']

                    # create entries for each relevant structure
                    for structure, wvnumber, wvtype in structures:
                    
#                        print structure
#                        print wvnumber
#                        print wvtype
                    
                        for entry_string, entry_value in structure:

#                            print entry_string
#                            print entry_value

                            # process every combination (as we don't know what replacements are in the entry_string)
                            used = []
                            for o_artist in o_artistlisttmp:
                                for artist in artistlisttmp:
                                    for o_albumartist in o_albumartistlisttmp:
                                        for albumartist in albumartistlisttmp:
                                            for o_composer in o_composerlisttmp:
                                                for composer in composerlisttmp:
                                                    for o_genre in o_genrelisttmp:
                                                        for genre in genrelisttmp:
                                                            for o_virtual in o_virtuallist:
                                                                for virtual in virtuallist:
                                                                    for o_work in o_worklist:
                                                                        for work in worklist:
                                                       
                                                                            entry = eval(entry_string).strip()
                                                                            entry_tuple = (wvnumber, entry, entry_value, albumtypestring, wvtype)
                                                                            if entry_tuple not in used:
                                                                                albumentries.append(entry_tuple)
                                                                                used.append(entry_tuple)




#need to make sure that old and new entries only contain the values from workvirtuals_update                    




                # set art at album level
                if coverart and coverart != '':
                    cover = coverart
                    artid = coverartid
                elif folderart and folderart != '' and prefer_folderart:
                    cover = folderart
                    artid = folderartid
                elif trackart and trackart != '':
                    cover = trackart
                    artid = trackartid
                else:
                    cover = ''
                    artid = ''

#                print albumentries

                # process album names
                # note that album_entry can contain either a virtual, a work, or a concatenated list of album names (albumliststringfull)
                for (album_tracknumber, album_entry, albumvalue_entry, albumtype_entry, albumoldnew_entry) in albumentries:
                
                    if albumoldnew_entry == 'old':
                        o_album = album_entry
                        o_albumtype = albumvalue_entry
                        album_updatetype = 'D'
                    else:
                        album = album_entry
                        albumtype = albumvalue_entry
                        album_updatetype = 'I'
                    albumtypestring = albumtype_entry
                
                    # album - one instance for all tracks from the album with the same album/artist/albumartist/duplicate/albumtype, with multi entry strings concatenated

                    # if we have a delete, delete the album if nothing else refers to it
                    # if we have an insert, insert the album if it doesn't already exist

                    if album_updatetype == 'D':

                        # for delete need album id
                        album_id = None
                        try:
                            cs2.execute("""select id, tracknumbers from albums where albumlist=? and artistlist=? and albumartistlist=? and duplicate=? and albumtype=?""",
#                                        (o_album, o_artistliststringfull, o_albumartistliststringfull, o_duplicate, o_albumtype))
                                        (o_album, o_artistliststring, o_albumartistliststring, o_duplicate, o_albumtype))
                            row = cs2.fetchone()
                            if row:
                                album_id, tracknumbers = row
                                if albumtypestring == 'album' and updatetype == 'U':
                                    # need to maintain this across update (delete/insert) for album
                                    prev_album_id = album_id
                                
                        except sqlite3.Error, e:
                            errorstring = "Error getting album id: %s" % e.args[0]
                            filelog.write_error(errorstring)

                        if album_id:
                            # check whether we are deleting a track that is the track we got the album details for
                            s_tracks = tracknumbers.split(',')
                            if len(s_tracks) != 1:
                                # more that one track associated with this album
                                album_tracknumberstring = str(album_tracknumber)
                                if album_tracknumberstring.strip() == '': album_tracknumberstring = 'n'
                                if s_tracks[0] == album_tracknumberstring:
                                    # either we set the album from the track we are deleting
                                    # or there are no tracknumbers
                                    # - we need to set the album from the next track in the list
                                    s_tracks.pop(0)
                                    new_track = s_tracks[0]
                                    tracknumbers = ','.join(s_tracks)
                                    if new_track == 'n': find_track = ''
                                    else: find_track = int(new_track)
                                    # for works and virtuals we want to retain the album details
                                    # as they are set from the .sp rather than a specific track
                                    if albumtypestring != 'album':
                                        try:
                                            albums = (tracknumbers, album_id)
                                            logstring = "UPDATE ALBUM: %s" % str(albums)
                                            filelog.write_verbose_log(logstring)
                                            cs2.execute("""update albums set 
                                                           tracknumbers=?
                                                           where id=?""", 
                                                           albums)
                                        except sqlite3.Error, e:
                                            errorstring = "Error resetting album details (workvirtual): %s" % e.args[0]
                                            filelog.write_error(errorstring)
                                    else:
                                        try:
                                            cs2.execute("""select year, folderart, trackart, folderartid, trackartid, inserted, composer, created, lastmodified, albumsort from tracks where album=? and artist=? and albumartist=? and duplicate=? and tracknumber=?""",
                                                        (o_album, o_artistliststring, o_albumartistliststring, o_duplicate, find_track))
                                            row = cs2.fetchone()
                                            # TODO: check why we sometimes don't get a row - probably related to 'the', which we have now fixed
                                            if row:
                                                n_year, n_folderart, n_trackart, n_folderartid, n_trackartid, n_inserted, n_composer, n_created, n_lastmodified, n_albumsort = row
                                            else:
                                                n_folderart = n_trackart = n_year = n_inserted = n_composer = n_created = n_lastmodified = n_albumsort = ''

                                        except sqlite3.Error, e:
                                            errorstring = "Error getting track details: %s" % e.args[0]
                                            filelog.write_error(errorstring)

                                        # set art
                                        if n_folderart and n_folderart != '' and prefer_folderart:
                                            n_cover = n_folderart
                                            n_artid = n_folderartid
                                        elif n_trackart and n_trackart != '':
                                            n_cover = n_trackart
                                            n_artid = n_trackartid
                                        else:
                                            n_cover = ''
                                            n_artid = ''

                                        try:
                                            albums = (n_year, n_cover, n_artid, n_inserted, n_composer, tracknumbers, n_created, n_lastmodified, n_albumsort, album_id)
                                            logstring = "UPDATE ALBUM: %s" % str(albums)
                                            filelog.write_verbose_log(logstring)
                                            cs2.execute("""update albums set 
                                                           year=?,
                                                           cover=?,
                                                           artid=?,
                                                           inserted=?,
                                                           composerlist=?,
                                                           tracknumbers=?,
                                                           created=?,
                                                           lastmodified=?,
                                                           albumsort=?
                                                           where id=?""", 
                                                           albums)
                                        except sqlite3.Error, e:
                                            errorstring = "Error resetting album details: %s" % e.args[0]
                                            filelog.write_error(errorstring)
                                
                                else:
                                    # we can just remove the track from the list and update the list
                                    s_tracks.remove(album_tracknumberstring)
                                    tracknumbers = ','.join(s_tracks)
                                    try:
                                        albums = (tracknumbers, album_id)
                                        logstring = "UPDATE ALBUM TRACKNUMBERS: %s" % str(albums)
                                        filelog.write_verbose_log(logstring)
                                        cs2.execute("""update albums set 
                                                       tracknumbers=?
                                                       where id=?""", 
                                                       albums)
                                    except sqlite3.Error, e:
                                        errorstring = "Error updating album tracknumbers: %s" % e.args[0]
                                        filelog.write_error(errorstring)

                            else:
                                # last track, can delete album                            
                                try:
                                    # only delete album if other tracks don't refer to it
#                                    delete = (o_album, o_artistliststringfull, o_albumartistliststringfull, o_duplicate, o_albumtype, album_id)
                                    delete = (o_album, o_artistliststring, o_albumartistliststring, o_duplicate, o_albumtype, album_id)
                                    logstring = "DELETE ALBUM: %s" % str(delete)
                                    filelog.write_verbose_log(logstring)
                                    cs2.execute("""delete from albums where not exists (select 1 from tracks where album=? and artist=? and albumartist=? and duplicate=? and albumtype=?) and id=?""", delete)
                                except sqlite3.Error, e:
                                    errorstring = "Error deleting album details: %s" % e.args[0]
                                    filelog.write_error(errorstring)

                    if album_updatetype == 'I':

                        try:
                            # check whether we already have this album (from a previous run or another track)
                            count = 0
                            cs2.execute("""select id, tracknumbers from albums where albumlist=? and artistlist=? and albumartistlist=? and duplicate=? and albumtype=?""",
#                                          (album, artistliststringfull, albumartistliststringfull, duplicate, albumtype))
                                          (album, artistliststring, albumartistliststring, duplicate, albumtype))
                            crow = cs2.fetchone()
                            if crow:
                                album_id, tracknumbers = crow
                                count = 1
                                # now process the tracknumbers
                                s_tracks = tracknumbers.split(',')
                                tracks = [int(t) for t in s_tracks if t != 'n']
                                n_tracks = [t for t in s_tracks if t == 'n']
                                if not tracks: lowest_track = None
                                else: lowest_track = tracks[0]
                                if album_tracknumber != '':
                                    tracks.append(album_tracknumber)
                                    tracks.sort()
                                else:
                                    n_tracks.append('n')
                                s_tracks = [str(t) for t in tracks]
                                s_tracks.extend(n_tracks)
                                tracknumbers = ','.join(s_tracks)
                                # check whether the track we are processing has a lower number than the lowest one we have stored
                                if not lowest_track or album_tracknumber < lowest_track:
#                                    albums = (album, artistliststringfull, year, albumartistliststringfull, duplicate, cover, artid, inserted, composerliststring, tracknumbers, created, lastmodified, albumtype, albumsort, album_id)
                                    albums = (album, artistliststring, year, albumartistliststring, duplicate, cover, artid, inserted, composerliststring, tracknumbers, created, lastmodified, albumtype, albumsort, album_id)
                                    logstring = "UPDATE ALBUM: %s" % str(albums)
                                    filelog.write_verbose_log(logstring)
                                    cs2.execute("""update albums set 
                                                   albumlist=?,
                                                   artistlist=?,
                                                   year=?,
                                                   albumartistlist=?,
                                                   duplicate=?,
                                                   cover=?,
                                                   artid=?,
                                                   inserted=?,
                                                   composerlist=?,
                                                   tracknumbers=?,
                                                   created=?,
                                                   lastmodified=?,
                                                   albumtype=?,
                                                   albumsort=?
                                                   where id=?""", 
                                                   albums)
                                else:
                                    # just store the tracknumber
                                    albums = (tracknumbers, album_id)
                                    logstring = "UPDATE ALBUM TRACKNUMBERS: %s" % str(albums)
                                    filelog.write_verbose_log(logstring)
                                    cs2.execute("""update albums set 
                                                   tracknumbers=?
                                                   where id=?""", 
                                                   albums)
                            if count == 0:
                                # insert base record
                                if albumtypestring == 'album' and updatetype == 'U':
#                                    album_id = prev_album_id
                                    album_id = None
                                else:
                                    album_id = None
                                tracknumbers = str(album_tracknumber)
                                if tracknumbers.strip() == '':
                                    tracknumbers = 'n'
#                                albums = (album_id, album, artistliststringfull, year, albumartistliststringfull, duplicate, cover, artid, inserted, composerliststring, tracknumbers, created, lastmodified, albumtype, '', '', albumsort)
                                albums = (album_id, album, artistliststring, year, albumartistliststring, duplicate, cover, artid, inserted, composerliststring, tracknumbers, created, lastmodified, albumtype, '', '', albumsort)
                                logstring = "INSERT ALBUM: %s" % str(albums)
                                filelog.write_verbose_log(logstring)
                                cs2.execute('insert into albums values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', albums)
                                album_id = cs2.lastrowid

                        except sqlite3.Error, e:
                            errorstring = "Error inserting/updating album details: %s" % e.args[0]
                            filelog.write_error(errorstring)

                    # we need to process non-concatenated album entries for lookups
                    # - virtuals and works are single entries so make into lists
                    #   (lists for normal albums already exist)
                    if albumtypestring != 'album':
                        # virtuals and works are single entries
                        if album_updatetype == 'D':
                            o_albumlist = [o_album]
                        elif album_updatetype == 'I':
                            albumlist = [album]
                    
                    # now save the albumlist/duplicate/albumtype for albumsonly processing at the end
                    # - we don't process them here as we only need to process them once per album
                    if album_updatetype == 'D':
                        albumsonlyentry = (o_album, o_duplicate, o_albumtype, o_albumsort, o_albumlist, album_updatetype, o_artistliststring, o_artistliststringfull, o_albumartistliststring, o_albumartistliststringfull)
                    else:
                        albumsonlyentry = (album, duplicate, albumtype, albumsort, albumlist, album_updatetype, artistliststring, artistliststringfull, albumartistliststring, albumartistliststringfull)
                    if not albumsonlyentry in albumsonlylist:
                        albumsonlylist += [albumsonlyentry]

                    # insert multiple entry lookups at album/track level if they don't already exist
                    # note that these can change by track, hence we do it outside of album (which may not change)

                    # if we have a delete, delete the lookup if nothing else refers to it
                    # if we have an insert, insert the lookup if it doesn't already exist
                    
                    if album_updatetype == 'D':

                        try:
                            # these lookups are unique on track id so nothing else refers to them (so just delete)
                            for o_album in o_albumlist:
                                for o_genre in o_genrelist:
                                    for o_artist in o_artistlist:
                                        delete = (track_rowid, o_genre, o_artist, album_id, o_duplicate, o_albumtype)
                                        logstring = "DELETE GenreArtistAlbumTrack: %s" % str(delete)
                                        filelog.write_verbose_log(logstring)
                                        cs2.execute("""delete from GenreArtistAlbumTrack where track_id=? and genre=? and artist=? and album_id=? and duplicate=? and albumtype=?""", delete)
                                    for o_albumartist in o_albumartistlist:
                                        delete = (track_rowid, o_genre, o_albumartist, album_id, o_duplicate, o_albumtype)
                                        logstring = "DELETE GenreAlbumartistAlbumTrack: %s" % str(delete)
                                        filelog.write_verbose_log(logstring)
                                        cs2.execute("""delete from GenreAlbumartistAlbumTrack where track_id=? and genre=? and albumartist=? and album_id=? and duplicate=? and albumtype=?""", delete)
                                for o_artist in o_artistlist:
                                    delete = (track_rowid, o_artist, album_id, o_duplicate, o_albumtype)
                                    logstring = "DELETE ArtistAlbumTrack:" + str(delete)
                                    filelog.write_verbose_log(logstring)
                                    cs2.execute("""delete from ArtistAlbumTrack where track_id=? and artist=? and album_id=? and duplicate=? and albumtype=?""", delete)
                                for o_albumartist in o_albumartistlist:
                                    delete = (track_rowid, o_albumartist, album_id, o_duplicate, o_albumtype)
                                    logstring = "DELETE AlbumartistAlbumTrack:" + str(delete)
                                    filelog.write_verbose_log(logstring)
                                    cs2.execute("""delete from AlbumartistAlbumTrack where track_id=? and albumartist=? and album_id=? and duplicate=? and albumtype=?""", delete)
                                for o_composer in o_composerlist:
                                    delete = (track_rowid, o_composer, album_id, o_duplicate, o_albumtype)
                                    logstring = "DELETE ComposerAlbumTrack:" + str(delete)
                                    filelog.write_verbose_log(logstring)
                                    cs2.execute("""delete from ComposerAlbumTrack where track_id=? and composer=? and album_id=? and duplicate=? and albumtype=?""", delete)

                            if albumtypestring == 'work' or albumtypestring == 'virtual':

                                for o_album in o_albumlist:
                                    for o_genre in o_genrelisttmp:
                                        for o_artist in o_artistlisttmp:
                                            for o_albumartist in o_albumartistlisttmp:
                                                for o_composer in o_composerlisttmp:

#                                                    delete = (track_rowid, o_genreliststring, o_artistliststringfull, o_albumartistliststringfull, o_originalalbum, o_album, o_composerliststringfull, o_duplicate, o_albumtype, album_tracknumber, o_coverart, o_coverartid)
                                                    delete = (track_rowid, o_genre, o_artist, o_albumartist, o_originalalbum, o_album, o_composer, o_duplicate, o_albumtype, album_tracknumber, o_coverart, o_coverartid)

                                                    logstring = "DELETE TrackNumbers:" + str(delete)
                                                    filelog.write_verbose_log(logstring)
                                                    cs2.execute("""delete from TrackNumbers where track_id=? and genre=? and artist=? and albumartist=? and album=? and dummyalbum=? and composer=? and duplicate=? and albumtype=? and tracknumber=? and coverart=? and coverartid=?""", delete)

                        except sqlite3.Error, e:
                            errorstring = "Error deleting lookup details: %s" % e.args[0]
                            filelog.write_error(errorstring)

                    if album_updatetype == 'I':

                        try:
                            for album in albumlist:
                                for genre in genrelist:
                                    for artist in artistlist:
                                        check = (track_rowid, genre, artist, album_id, duplicate, albumtype)
                                        cs2.execute("""select * from GenreArtistAlbumTrack where track_id=? and genre=? and artist=? and album_id=? and duplicate=? and albumtype=?""", check)
                                        crow = cs2.fetchone()
                                        if not crow:
                                            insert = (track_rowid, genre, artist, album, album_id, duplicate, albumtype)
                                            logstring = "INSERT GenreArtistAlbumTrack: %s" % str(insert)
                                            filelog.write_verbose_log(logstring)
                                            cs2.execute('insert into GenreArtistAlbumTrack values (?,?,?,?,?,?,?)', insert)
                                    for albumartist in albumartistlist:
                                        check = (track_rowid, genre, albumartist, album_id, duplicate, albumtype)
                                        cs2.execute("""select * from GenreAlbumartistAlbumTrack where track_id=? and genre=? and albumartist=? and album_id=? and duplicate=? and albumtype=?""", check)
                                        crow = cs2.fetchone()
                                        if not crow:
                                            insert = (track_rowid, genre, albumartist, album, album_id, duplicate, albumtype)
                                            logstring = "INSERT GenreAlbumartistAlbumTrack: %s" % str(insert)
                                            filelog.write_verbose_log(logstring)
                                            cs2.execute('insert into GenreAlbumartistAlbumTrack values (?,?,?,?,?,?,?)', insert)
                                for artist in artistlist:
                                    check = (track_rowid, artist, album_id, duplicate, albumtype)
                                    cs2.execute("""select * from ArtistAlbumTrack where track_id=? and artist=? and album_id=? and duplicate=? and albumtype=?""", check)
                                    crow = cs2.fetchone()
                                    if not crow:
                                        insert = (track_rowid, artist, album, album_id, duplicate, albumtype)
                                        logstring = "INSERT ArtistAlbumTrack:" + str(insert)
                                        filelog.write_verbose_log(logstring)
                                        cs2.execute('insert into ArtistAlbumTrack values (?,?,?,?,?,?)', insert)
                                for albumartist in albumartistlist:
                                    check = (track_rowid, albumartist, album_id, duplicate, albumtype)
                                    cs2.execute("""select * from AlbumartistAlbumTrack where track_id=? and albumartist=? and album_id=? and duplicate=? and albumtype=?""", check)
                                    crow = cs2.fetchone()
                                    if not crow:
                                        insert = (track_rowid, albumartist, album, album_id, duplicate, albumtype)
                                        logstring = "INSERT AlbumartistAlbumTrack:" + str(insert)
                                        filelog.write_verbose_log(logstring)
                                        cs2.execute('insert into AlbumartistAlbumTrack values (?,?,?,?,?,?)', insert)
                                for composer in composerlist:
                                    check = (track_rowid, composer, album_id, duplicate, albumtype)
                                    cs2.execute("""select * from ComposerAlbumTrack where track_id=? and composer=? and album_id=? and duplicate=? and albumtype=?""", check)
                                    crow = cs2.fetchone()
                                    if not crow:
                                        insert = (track_rowid, composer, album, album_id, duplicate, albumtype)
                                        logstring = "INSERT ComposerAlbumTrack:" + str(insert)
                                        filelog.write_verbose_log(logstring)
                                        cs2.execute('insert into ComposerAlbumTrack values (?,?,?,?,?,?)', insert)

                            if albumtypestring == 'work' or albumtypestring == 'virtual':

                                for album in albumlist:
                                    for genre in genrelisttmp:
                                        for artist in artistlisttmp:
                                            for albumartist in albumartistlisttmp:
                                                for composer in composerlisttmp:

#                                                    check = (track_rowid, genreliststring, artistliststringfull, albumartistliststringfull, originalalbum, album, composerliststringfull, duplicate, albumtype, album_tracknumber, coverart, coverartid)
                                                    check = (track_rowid, genre, artist, albumartist, originalalbum, album, composer, duplicate, albumtype, album_tracknumber, coverart, coverartid)
                                                    cs2.execute("""select * from TrackNumbers where track_id=? and genre=? and artist=? and albumartist=? and album=? and dummyalbum=? and composer=? and duplicate=? and albumtype=? and tracknumber=? and coverart=? and coverartid=?""", check)
                                                    crow = cs2.fetchone()
                                                    if not crow:
                                                        insert = check
                                                        logstring = "INSERT TrackNumbers:" + str(insert)
                                                        filelog.write_verbose_log(logstring)
                                                        cs2.execute('insert into TrackNumbers values (?,?,?,?,?,?,?,?,?,?,?,?)', insert)

                        except sqlite3.Error, e:
                            errorstring = "Error inserting album/track lookup details: %s" % e.args[0]
                            filelog.write_error(errorstring)

                    # insert multiple entry lookups at artist/album level if they don't already exist
                    # note that these can change by track, hence we do it outside of artist (which may not change)

                    # if we have a delete, delete the lookup if nothing else refers to it
                    # if we have an insert, insert the lookup if it doesn't already exist

                    if album_updatetype == 'D':

                        try:
                            for o_album in o_albumlist:
                                for o_genre in o_genrelist:
                                    for o_artist in o_artistlist:
                                        delete = (o_genre, o_artist, o_genre, o_artist)
                                        logstring = "DELETE GenreArtist:" + str(delete)
                                        filelog.write_verbose_log(logstring)
                                        cs2.execute("""delete from GenreArtist where not exists (select 1 from GenreArtistAlbum where genre=? and artist=?) and genre=? and artist=?""", delete)
                                        delete = (o_genre, o_artist, album_id, o_duplicate, o_albumtype, album_id)
                                        logstring = "DELETE GenreArtistAlbum:" + str(delete)
                                        filelog.write_verbose_log(logstring)
                                        cs2.execute("""delete from GenreArtistAlbum where not exists (select 1 from GenreArtistAlbumTrack where genre=? and artist=? and album_id=? and duplicate=? and albumtype=?) and album_id=?""", delete)
                                    for o_albumartist in o_albumartistlist:
                                        delete = (o_genre, o_albumartist, o_genre, o_albumartist)
                                        logstring = "DELETE GenreAlbumartist:" + str(delete)
                                        filelog.write_verbose_log(logstring)
                                        cs2.execute("""delete from GenreAlbumartist where not exists (select 1 from GenreAlbumartistAlbum where genre=? and albumartist=?) and genre=? and albumartist=?""", delete)
                                        delete = (o_genre, o_albumartist, album_id, o_duplicate, o_albumtype, album_id)
                                        logstring = "DELETE GenreAlbumartistAlbum:" + str(delete)
                                        filelog.write_verbose_log(logstring)
                                        cs2.execute("""delete from GenreAlbumartistAlbum where not exists (select 1 from GenreAlbumartistAlbumTrack where genre=? and albumartist=? and album_id=? and duplicate=? and albumtype=?) and album_id=?""", delete)
                                for o_artist in o_artistlist:
                                    delete = (o_artist, album_id, o_duplicate, o_albumtype, album_id)
                                    logstring = "DELETE ArtistAlbum:" + str(delete)
                                    filelog.write_verbose_log(logstring)
                                    cs2.execute("""delete from ArtistAlbum where not exists (select 1 from ArtistAlbumTrack where artist=? and album_id=? and duplicate=? and albumtype=?) and album_id=?""", delete)
                                for o_albumartist in o_albumartistlist:
                                    delete = (o_albumartist, album_id, o_duplicate, o_albumtype, album_id)
                                    logstring = "DELETE AlbumartistAlbum:" + str(delete)
                                    filelog.write_verbose_log(logstring)
                                    cs2.execute("""delete from AlbumartistAlbum where not exists (select 1 from AlbumartistAlbumTrack where albumartist=? and album_id=? and duplicate=? and albumtype=?) and album_id=?""", delete)
                                for o_composer in o_composerlist:
                                    delete = (o_composer, album_id, o_duplicate, o_albumtype, album_id)
                                    logstring = "DELETE ComposerAlbum:" + str(delete)
                                    filelog.write_verbose_log(logstring)
                                    cs2.execute("""delete from ComposerAlbum where not exists (select 1 from ComposerAlbumTrack where composer=? and album_id=? and duplicate=? and albumtype=?) and album_id=?""", delete)
                        except sqlite3.Error, e:
                            errorstring = "Error deleting (genre)/(artist/albumartist/composer)/artist lookup details: %s" % e.args[0]
                            filelog.write_error(errorstring)

                    if album_updatetype == 'I':

                        try:
                            for album in albumlist:
                                for genre in genrelist:
                                    for artist in artistlist:
                                        check = (genre, artist)
                                        cs2.execute("""select * from GenreArtist where genre=? and artist=?""", check)
                                        crow = cs2.fetchone()
                                        if not crow:
                                            insert = check + ('', '')
                                            logstring = "INSERT GenreArtist: %s" % str(insert)
                                            filelog.write_verbose_log(logstring)
                                            cs2.execute('insert into GenreArtist values (?,?,?,?)', insert)
                                        check = (album_id, genre, artist, album, duplicate, albumtype, artistsort)
                                        cs2.execute("""select * from GenreArtistAlbum where album_id=? and genre=? and artist=? and album=? and duplicate=? and albumtype=? and artistsort=?""", check)
                                        crow = cs2.fetchone()
                                        if not crow:
                                            insert = check + ('', '')
                                            logstring = "INSERT GenreArtistAlbum: %s" % str(insert)
                                            filelog.write_verbose_log(logstring)
                                            cs2.execute('insert into GenreArtistAlbum values (?,?,?,?,?,?,?,?,?)', insert)
                                    for albumartist in albumartistlist:
                                        check = (genre, albumartist)
                                        cs2.execute("""select * from GenreAlbumartist where genre=? and albumartist=?""", check)
                                        crow = cs2.fetchone()
                                        if not crow:
                                            insert = check + ('', '')
                                            logstring = "INSERT GenreAlbumartist: %s" % str(insert)
                                            filelog.write_verbose_log(logstring)
                                            cs2.execute('insert into GenreAlbumartist values (?,?,?,?)', insert)
                                        check = (album_id, genre, albumartist, album, duplicate, albumtype, albumartistsort)
                                        cs2.execute("""select * from GenreAlbumartistAlbum where album_id=? and genre=? and albumartist=? and album=? and duplicate=? and albumtype=? and albumartistsort=?""", check)
                                        crow = cs2.fetchone()
                                        if not crow:
                                            insert = check + ('', '')
                                            logstring = "INSERT GenreAlbumartistAlbum: %s" % str(insert)
                                            filelog.write_verbose_log(logstring)
                                            cs2.execute('insert into GenreAlbumartistAlbum values (?,?,?,?,?,?,?,?,?)', insert)
                                for artist in artistlist:
                                    check = (album_id, artist, album, duplicate, albumtype, artistsort)
                                    cs2.execute("""select * from ArtistAlbum where album_id=? and artist=? and album=? and duplicate=? and albumtype=? and artistsort=?""", check)
                                    crow = cs2.fetchone()
                                    if not crow:
                                        insert = check + ('', '')
                                        logstring = "INSERT ArtistAlbum:" + str(insert)
                                        filelog.write_verbose_log(logstring)
                                        cs2.execute('insert into ArtistAlbum values (?,?,?,?,?,?,?,?)', insert)
                                for albumartist in albumartistlist:
                                    check = (album_id, albumartist, album, duplicate, albumtype, albumartistsort)
                                    cs2.execute("""select * from AlbumartistAlbum where album_id=? and albumartist=? and album=? and duplicate=? and albumtype=? and albumartistsort=?""", check)
                                    crow = cs2.fetchone()
                                    if not crow:
                                        insert = check + ('', '')
                                        logstring = "INSERT AlbumartistAlbum:" + str(insert)
                                        filelog.write_verbose_log(logstring)
                                        cs2.execute('insert into AlbumartistAlbum values (?,?,?,?,?,?,?,?)', insert)
                                for composer in composerlist:
                                    check = (album_id, composer, album, duplicate, albumtype, composersort)
                                    cs2.execute("""select * from ComposerAlbum where album_id=? and composer=? and album=? and duplicate=? and albumtype=? and composersort=?""", check)
                                    crow = cs2.fetchone()
                                    if not crow:
                                        insert = check + ('', '')
                                        logstring = "INSERT ComposerAlbum:" + str(insert)
                                        filelog.write_verbose_log(logstring)
                                        cs2.execute('insert into ComposerAlbum values (?,?,?,?,?,?,?,?)', insert)
                        except sqlite3.Error, e:
                            errorstring = "Error inserting (genre)/(artist/albumartist/composer)/album lookup details: %s" % e.args[0]
                            filelog.write_error(errorstring)

                # artist - one instance for all artists on a track

                # if we have an update
                #     if the key fields have changed, process as a delete and an insert
                #     else update the non key fields if they have changed
                # if we have a delete, delete the artist if nothing else refers to it
                # if we have an insert, insert the artist if it doesn't already exist

                artist_change = False
                if updatetype == 'U':
                
                    # check whether artist has changed
                    if o_artistliststring != artistliststring:
                        artist_change = True
                    else:
                        # there is nothing to change outside the keys fields
                        # so there can't be an update
                        pass

                for o_artist in o_artistlist:

                    if updatetype == 'D' or artist_change:

                        try:
                            # only delete artist if other tracks don't refer to it
                            delete = (o_artist, o_artist)
                            logstring = "DELETE ARTIST: %s" % o_artist
                            filelog.write_verbose_log(logstring)
                            cs2.execute("""delete from Artist where not exists (select 1 from ArtistAlbumTrack where artist=?) and artist=?""", delete)
                        except sqlite3.Error, e:
                            errorstring = "Error deleting artist details: %s" % e.args[0]
                            filelog.write_error(errorstring)

                for artist in artistlist:
                    
                    if updatetype == 'I' or artist_change:

                        try:
                            # check whether we already have this artist (from a previous run or another track)
                            cs2.execute("""select artist from Artist where artist=?""", (artist, ))
                            crow = cs2.fetchone()
                            if not crow:
                                artists = (None, artist, '', '')
                                logstring = "INSERT ARTIST: %s" % str(artists)
                                filelog.write_verbose_log(logstring)
                                cs2.execute('insert into Artist values (?,?,?,?)', artists)
                        except sqlite3.Error, e:
                            errorstring = "Error inserting artist details: %s" % e.args[0]
                            filelog.write_error(errorstring)

                # albumartist - one instance for all albumartists on a track
                
                # if we have an update
                #     if the key fields have changed, process as a delete and an insert
                #     else update the non key fields if they have changed
                # if we have a delete, delete the artist if nothing else refers to it
                # if we have an insert, insert the artist if it doesn't already exist

                albumartist_change = False
                if updatetype == 'U':
                
                    # check whether artist has changed
                    if o_albumartistliststring != albumartistliststring:
                        albumartist_change = True
                    else:
                        # there is nothing to change outside the keys fields
                        # so there can't be an update
                        pass

                for o_albumartist in o_albumartistlist:

                    if updatetype == 'D' or albumartist_change:

                        try:
                            # only delete albumartist if other tracks don't refer to it
                            delete = (o_albumartist, o_albumartist)
                            logstring = "DELETE ALBUMARTIST: %s" % o_albumartist
                            filelog.write_verbose_log(logstring)
                            cs2.execute("""delete from Albumartist where not exists (select 1 from AlbumartistAlbumTrack where albumartist=?) and albumartist=?""", delete)
                        except sqlite3.Error, e:
                            errorstring = "Error deleting albumartist details: %s" % e.args[0]
                            filelog.write_error(errorstring)

                for albumartist in albumartistlist:
                    
                    if updatetype == 'I' or albumartist_change:

                        try:
                            # check whether we already have this albumartist (from a previous run or another track)
                            cs2.execute("""select albumartist from Albumartist where albumartist=?""", (albumartist, ))
                            crow = cs2.fetchone()
                            if not crow:
                                albumartists = (None, albumartist, '', '')
                                logstring = "INSERT ALBUMARTIST: %s" % str(albumartists)
                                filelog.write_verbose_log(logstring)
                                cs2.execute('insert into Albumartist values (?,?,?,?)', albumartists)
                        except sqlite3.Error, e:
                            errorstring = "Error inserting albumartist details: %s" % e.args[0]
                            filelog.write_error(errorstring)

                # composer - one instance for all composers on a track

                # if we have an update
                #     if the key fields have changed, process as a delete and an insert
                #     else update the non key fields if they have changed
                # if we have a delete, delete the composer if nothing else refers to it
                # if we have an insert, insert the composer if it doesn't already exist

                composer_change = False
                if updatetype == 'U':
                
                    # check whether composer has changed
                    if o_composerliststring != composerliststring:
                        composer_change = True
                    else:
                        # there is nothing to change outside the keys fields
                        # so there can't be an update
                        pass

                for o_composer in o_composerlist:

                    if updatetype == 'D' or composer_change:

                        try:
                            # only delete composer if other tracks don't refer to it
                            delete = (o_composer, o_composer)
                            logstring = "DELETE COMPOSER: %s" % o_composer
                            filelog.write_verbose_log(logstring)
                            cs2.execute("""delete from Composer where not exists (select 1 from ComposerAlbumTrack where composer=?) and composer=?""", delete)
                        except sqlite3.Error, e:
                            errorstring = "Error deleting composer details: %s" % e.args[0]
                            filelog.write_error(errorstring)

                for composer in composerlist:
                    
                    if updatetype == 'I' or composer_change:

                        try:
                            # check whether we already have this composer (from a previous run or another track)
                            cs2.execute("""select composer from Composer where composer=?""", (composer, ))
                            crow = cs2.fetchone()
                            if not crow:
                                composers = (None, composer, '', '')
                                logstring = "INSERT COMPOSER: %s" % str(composers)
                                filelog.write_verbose_log(logstring)
                                cs2.execute('insert into Composer values (?,?,?,?)', composers)
                        except sqlite3.Error, e:
                            errorstring = "Error inserting composer details: %s" % e.args[0]
                            filelog.write_error(errorstring)

                # genre - one instance for all genres on a track

                # if we have an update
                #     if the key fields have changed, process as a delete and an insert
                #     else update the non key fields if they have changed
                # if we have a delete, delete the genre if nothing else refers to it
                # if we have an insert, insert the genre if it doesn't already exist

                genre_change = False
                if updatetype == 'U':
                
                    # check whether composer has changed
                    if o_genreliststring != genreliststring:
                        genre_change = True
                    else:
                        # there is nothing to change outside the keys fields
                        # so there can't be an update
                        pass

                for o_genre in o_genrelist:

                    if updatetype == 'D' or genre_change:

                        try:
                            # only delete genre if other tracks don't refer to it
                            delete = (o_genre, o_genre, o_genre)
                            logstring = "DELETE GENRE: %s" % o_genre
                            filelog.write_verbose_log(logstring)
                            cs2.execute("""
                                        delete from Genre where not exists (
                                        select 1 from GenreArtistAlbumTrack where genre=?
                                        union all
                                        select 1 from GenreAlbumartistAlbumTrack where genre=?
                                        ) and Genre=?
                                        """, delete)
                        except sqlite3.Error, e:
                            errorstring = "Error deleting genre details: %s" % e.args[0]
                            filelog.write_error(errorstring)

                for genre in genrelist:
                    
                    if updatetype == 'I' or genre_change:

                        try:
                            # check whether we already have this genre (from a previous run or another track)
                            cs2.execute("""select genre from Genre where genre=?""", (genre, ))
                            crow = cs2.fetchone()
                            if not crow:
                                genres = (None, genre, '', '')
                                logstring = "INSERT GENRE: %s" % str(genres)
                                filelog.write_verbose_log(logstring)
                                cs2.execute('insert into Genre values (?,?,?,?)', genres)
                        except sqlite3.Error, e:
                            errorstring = "Error inserting genre details: %s" % e.args[0]
                            filelog.write_error(errorstring)

            # now process albums where artist and albumartist are not used to differentiate i.e. albumsonly
            # - select all albums that match and combine their track entries
            # note that we do allow an exceptions list
            for album, duplicate, albumtype, albumsort, albumlist, album_updatetype, artistlist, artistlistfull, albumartistlist, albumartistlistfull in albumsonlylist:
            
                try:

                    # check for albumsonly exceptions
                    keep_albums_separate = False
                    separate_value = 0
                    for lalbum in albumlist:
                        if lalbum in separate_album_list:
                            keep_albums_separate = True
                            separate_value = 1

                    if album_updatetype == 'D':
                
                        # album has been deleted
                        # delete albumonly if it exists
                        
                        if keep_albums_separate:
                        
                            delete = (album, artistlist, albumartistlist, duplicate, albumtype)
                            logstring = "DELETE ALBUMONLY: %s" % str(delete)
                            filelog.write_verbose_log(logstring)
                            cs2.execute("""delete from albumsonly where albumlist=? and artistlist=? and albumartistlist=? and duplicate=? and albumtype=?""", delete)

                            # process albumsonly lookups
                            for lalbum in albumlist:
                                delete = (lalbum, artistlist, duplicate, albumtype)
                                logstring = "DELETE ArtistAlbumsonly:" + str(delete)
                                filelog.write_verbose_log(logstring)
                                cs2.execute("""delete from ArtistAlbumsonly where album=? and artist=? and duplicate=? and albumtype=?""", delete)
                                delete = (lalbum, albumartistlist, duplicate, albumtype)
                                logstring = "DELETE AlbumartistAlbumsonly:" + str(delete)
                                filelog.write_verbose_log(logstring)
                                cs2.execute("""delete from AlbumartistAlbumsonly where album=? and albumartist=? and duplicate=? and albumtype=?""", delete)

                        else:

                            delete = (album, duplicate, albumtype)
                            logstring = "DELETE ALBUMONLY: %s" % str(delete)
                            filelog.write_verbose_log(logstring)
                            cs2.execute("""delete from albumsonly where albumlist=? and duplicate=? and albumtype=?""", delete)

                            # process albumsonly lookups
                            for lalbum in albumlist:
                                delete = (lalbum, duplicate, albumtype)
                                logstring = "DELETE ArtistAlbumsonly:" + str(delete)
                                filelog.write_verbose_log(logstring)
                                cs2.execute("""delete from ArtistAlbumsonly where album=? and duplicate=? and albumtype=?""", delete)
                                logstring = "DELETE AlbumartistAlbumsonly:" + str(delete)
                                filelog.write_verbose_log(logstring)
                                cs2.execute("""delete from AlbumartistAlbumsonly where album=? and duplicate=? and albumtype=?""", delete)

                    else:

                        # insert/update
                        if keep_albums_separate:
                            cs2.execute("""select * from albums where albumlist=? and artistlist=? and albumartistlist=? and duplicate=? and albumtype=? order by tracknumbers""",
                                          (album, artistlist, albumartistlist, duplicate, albumtype))
                        else:
                            cs2.execute("""select * from albums where albumlist=? and duplicate=? and albumtype=? order by tracknumbers""",
                                          (album, duplicate, albumtype))

                        if keep_albums_separate:

                            crow = cs2.fetchone()
                            if crow:    # must be found
                                a_id, a_album, a_artist, a_year, a_albumartist, a_duplicate, a_cover, a_artid, a_inserted, a_composer, a_tracknumbers, a_created, a_lastmodified, a_albumtype, a_lastplayed, a_playcount, a_albumsort = crow

                        else:

                            # process tracknumbers
                            all_tracknumbers = []
                            lowest_tracknumbers = 'z'
                            for crow in cs2:
                                if crow[10] < lowest_tracknumbers:
                                    a_id, a_album, a_artist, a_year, a_albumartist, a_duplicate, a_cover, a_artid, a_inserted, a_composer, a_tracknumbers, a_created, a_lastmodified, a_albumtype, a_lastplayed, a_playcount, a_albumsort = crow
                                    lowest_tracknumbers = crow[10]
                                all_tracknumbers += crow[10].split(',')

                            # sort tracknumbers
                            all_tracknumbers = sorted(all_tracknumbers, tracknumbers_cmp)
                            all_tracknumbers = ','.join(all_tracknumbers)
                            a_tracknumbers = all_tracknumbers

                        # check if albumsonly exists
                        if keep_albums_separate:
                            cs2.execute("""select id from albumsonly where albumlist=? and artistlist=? and albumartistlist=? and duplicate=? and albumtype=?""",
                                          (album, artistlist, albumartistlist, duplicate, albumtype))
                        else:
                            cs2.execute("""select id from albumsonly where albumlist=? and duplicate=? and albumtype=?""",
                                          (album, duplicate, albumtype))
                        crow = cs2.fetchone()
                        if crow:
                        
                            # albumsonly exists, update it
                            a_album_id, = crow

                            albums = (a_album, a_artist, a_year, a_albumartist, a_duplicate, a_cover, a_artid, a_inserted, a_composer, a_tracknumbers, a_created, a_lastmodified, a_albumtype, a_albumsort, separate_value, a_album_id)
                            
                            logstring = "UPDATE ALBUMSONLY: %s" % str(albums)
                            filelog.write_verbose_log(logstring)
                            cs2.execute("""update albumsonly set
                                           albumlist=?,
                                           artistlist=?,
                                           year=?,
                                           albumartistlist=?,
                                           duplicate=?,
                                           cover=?,
                                           artid=?,
                                           inserted=?,
                                           composerlist=?,
                                           tracknumbers=?,
                                           created=?,
                                           lastmodified=?,
                                           albumtype=?,
                                           albumsort=?,
                                           separated=?
                                           where id=?""",
                                           albums)
                        else:
                            # insert albumonly
                            albums = (None, a_album, a_artist, a_year, a_albumartist, a_duplicate, a_cover, a_artid, a_inserted, a_composer, a_tracknumbers, a_created, a_lastmodified, a_albumtype, a_lastplayed, a_playcount, a_albumsort, separate_value)
                            logstring = "INSERT ALBUMSONLY: %s" % str(albums)
                            filelog.write_verbose_log(logstring)
                            cs2.execute('insert into albumsonly values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', albums)
                            a_album_id = cs2.lastrowid

                        # process albumsonly lookups
                        if keep_albums_separate:
                            for lalbum in albumlist:
                                check = (a_album_id, lalbum, artistlist, duplicate, albumtype, albumsort)
                                cs2.execute("""select * from ArtistAlbumsonly where album_id=? and album=? and artist=? and duplicate=? and albumtype=? and albumsort=?""", check)
                                crow = cs2.fetchone()
                                if not crow:
                                    insert = a_album_id, lalbum, a_artist, duplicate, albumtype, albumsort, '', ''
                                    logstring = "INSERT ArtistAlbumsonly:" + str(insert)
                                    filelog.write_verbose_log(logstring)
                                    cs2.execute('insert into ArtistAlbumsonly values (?,?,?,?,?,?,?,?)', insert)
                                check = (a_album_id, lalbum, albumartistlist, duplicate, albumtype, albumsort)
                                cs2.execute("""select * from AlbumartistAlbumsonly where album_id=? and album=? and albumartist=? and duplicate=? and albumtype=? and albumsort=?""", check)
                                crow = cs2.fetchone()
                                if not crow:
                                    insert = a_album_id, lalbum, a_albumartist, duplicate, albumtype, albumsort, '', ''
                                    logstring = "INSERT AlbumartistAlbumsonly:" + str(insert)
                                    filelog.write_verbose_log(logstring)
                                    cs2.execute('insert into AlbumartistAlbumsonly values (?,?,?,?,?,?,?,?)', insert)
                        else:
                            for lalbum in albumlist:
                                check = (a_album_id, lalbum, duplicate, albumtype, albumsort)
                                cs2.execute("""select * from ArtistAlbumsonly where album_id=? and album=? and duplicate=? and albumtype=? and albumsort=?""", check)
                                crow = cs2.fetchone()
                                if not crow:
                                    insert = a_album_id, lalbum, a_artist, duplicate, albumtype, albumsort, '', ''
                                    logstring = "INSERT ArtistAlbumsonly:" + str(insert)
                                    filelog.write_verbose_log(logstring)
                                    cs2.execute('insert into ArtistAlbumsonly values (?,?,?,?,?,?,?,?)', insert)
                                check = (a_album_id, lalbum, duplicate, albumtype, albumsort)
                                cs2.execute("""select * from AlbumartistAlbumsonly where album_id=? and album=? and duplicate=? and albumtype=? and albumsort=?""", check)
                                crow = cs2.fetchone()
                                if not crow:
                                    insert = a_album_id, lalbum, a_albumartist, duplicate, albumtype, albumsort, '', ''
                                    logstring = "INSERT AlbumartistAlbumsonly:" + str(insert)
                                    filelog.write_verbose_log(logstring)
                                    cs2.execute('insert into AlbumartistAlbumsonly values (?,?,?,?,?,?,?,?)', insert)

                except sqlite3.Error, e:
                    errorstring = "Error updating albumonly details: %s" % e.args[0]
                    filelog.write_error(errorstring)

            # post process playlist records to update track_id with rowid from tracks table
            try:
                cs2.execute("""update playlists set track_rowid = (select rowid from tracks where tracks.id = playlists.track_id)""")
                crow = cs2.fetchone()
            except sqlite3.Error, e:
                errorstring = "Error updating playlist ids: %s" % e.args[0]
                filelog.write_error(errorstring)

            # TODO:
            # when we add playcounts, we'll need to regenerate them for lookups that we deleted then reinserted

        except KeyboardInterrupt: 
            raise
#        except Exception, err: 
#            print str(err)

        logstring = "committing"
        filelog.write_verbose_log(logstring)
        db2.commit()

    cs1.close()

    if not options.quiet and not options.verbose:
        out = "\n"
        sys.stderr.write(out)
        sys.stderr.flush()

    # tidy up scan records
    scan_count = 0
    for scan_row in scan_details:
        scan_id, scan_path = scan_row
        scan_count += 1
        if options.scancount != None:   # need to be able to process zero
            if scan_count > options.scancount:
                break
        # remove the scan record and associated update records
        try:
            delete = (scan_id, scan_path)
            logstring = "DELETE SCAN: %s" % str(delete)
            filelog.write_verbose_log(logstring)
            cs2.execute("""delete from scans where id=? and scanpath=?""", delete)
            delete = (scan_id, )
            logstring = "DELETE TAGS UPDATES: %s" % str(delete)
            filelog.write_verbose_log(logstring)
            cs2.execute("""delete from tags_update where scannumber=?""", delete)
            logstring = "DELETE WORKVIRTUALS UPDATES: %s" % str(delete)
            filelog.write_verbose_log(logstring)
            cs2.execute("""delete from workvirtuals_update where scannumber=?""", delete)
        except sqlite3.Error, e:
            errorstring = "Error deleting scan/update details: %s" % e.args[0]
            filelog.write_error(errorstring)

    # update the container update ID
    if last_scan_stamp > 1:            
        try:
            params = (last_scan_stamp, scan_id)
            logstring = "UPDATE PARAMS: %s" % str(params)
            filelog.write_verbose_log(logstring)
            cs2.execute("""update params set
                           lastscanstamp=?, lastscanid=? 
                           where key='1'""", 
                           params)
        except sqlite3.Error, e:
            errorstring = "Error updating lastscanid details: %s" % e.args[0]
            filelog.write_error(errorstring)

    db2.commit()
    
    # update stats
    try:
        cs2.execute("""analyze""")
    except sqlite3.Error, e:
        errorstring = "Error updating stats: %s" % e.args[0]
        filelog.write_error(errorstring)

    db2.commit()
    
    cs2.close()

    logstring = "Tags processed"
    filelog.write_log(logstring)

    logstring = "finished"
    filelog.write_verbose_log(logstring)

def makeint(number):
    try:
        i = int(float(number))
    except Exception, e:
        i = 0
    return i

def tracknumbers_cmp(a, b):
    if a == 'n' and b == 'n': return 0
    elif a == 'n': return 1
    elif b == 'n': return -1
    else: return cmp(int(a), int(b))

def split_on_comma(string):
    # strings in string to be split can contain commas, but will be escaped with \
    tstring = string.replace('\,', '~%^@#')
    splitstring = tstring.split(',')
    splitstring = [e.replace('~%^@#', ',').strip() for e in splitstring]
    splitstring = [e for e in splitstring if e != '']
    return splitstring    

def remove_sep(liststring):
    # remove multiple consecutive separators
    liststring = re.sub('(%s)+' % MULTI_SEPARATOR, MULTI_SEPARATOR, liststring)
    if liststring.endswith(MULTI_SEPARATOR): liststring = liststring[:-1]
    # remove control characters (but not \n)
    multi = liststring.split(MULTI_SEPARATOR)
    multi = remove_ctrl(multi)
    liststring = MULTI_SEPARATOR.join(multi)
    return liststring

cmap = dict.fromkeys(range(32))
def remove_ctrl(liststring):
    # remove control characters - added as one user had garbage in some tags which broke an index
    liststring2 = []    
    for entry in liststring:
        entry = entry.translate(cmap)
        if entry != '': liststring2.append(entry)
    return liststring2

def unwrap_list(liststring, multi_field_separator, include, the_processing):
    # passed string can be multiple separator separated entries within multiple separator separated entries
    # e.g. 'artist1 \n artist2 ; artist3 \n artist4 ; artist5' (spaces shown only for clarity)
    #      separate artist tags separated by '\n' (MULTI_SEPARATOR)
    #      separate artists within a tag separated by ';' (multi_field_separator)

    # first remove multiple consecutive separators
    liststring = re.sub('(%s)+' % MULTI_SEPARATOR, MULTI_SEPARATOR, liststring)
    if liststring.endswith(MULTI_SEPARATOR): liststring = liststring[:-1]
    # now split out separate tags
    multi = liststring.split(MULTI_SEPARATOR)
    # now split each tag
    if multi_field_separator == '':
        multilist = multi
    else:
        multilist = []
        for entry in multi:
            entrylist = re.split('%s' % multi_field_separator, entry)
            entrylist = [e.strip() for e in entrylist]
            entrylist = [e for e in entrylist if e != '']
            multilist.extend(entrylist)

    # remove control characters
    multilist = remove_ctrl(multilist)            
            
    # select the entries we want
    if len(multilist) == 0:
        newlist = multilist
    elif include == 'first': 
        newlist = [multilist[0]]
    elif include == 'last': 
        newlist [multilist[-1]]
    else: 
        newlist = multilist
        
    # recreate the original string with just the selected entries in
    # with all separators converted
    liststring = MULTI_SEPARATOR.join(newlist)

    # perform 'the' processing on list
    if the_processing == 'after' or the_processing == 'remove':
        newlist = process_list_the(newlist, the_processing)

    # recreate the original string with just the selected entries in
    newstring = MULTI_SEPARATOR.join(newlist)

    # return both the updated original string and the corresponding list
    return liststring, newstring, newlist
    
def process_list_the(plist, the_processing):
    newlist = []
    for entry in plist:
        if entry.lower().startswith("the ") and entry.lower() != "the the":
            postentry = entry[4:]
            if the_processing == 'after':
                preentry = entry[0:3]
                newentry = postentry + ", " + preentry
            else: # 'remove'
                newentry = postentry
            newlist.append(newentry)
        else:
            newlist.append(entry)
    return newlist

def adjust_year(year, filespec):
    # convert year to ordinal date
    ordinal = None
    try:
        yeardatetime = parsedate(year, default=DEFAULTDATE)
        if yeardatetime.year != 1:
            ordinal = yeardatetime.toordinal()
    except Exception:
        # don't really care why parsedate failed
        # have another go at finding the century
        cccc = None
        datefacets = re.split('\D', year)
        for i in range(len(datefacets), 0, -1):
            chars = datefacets[i-1]
            if len(chars) == 4:
                cccc = int(chars)
                break
        if not cccc:
            warningstring = "Warning processing track: %s : tag: %s : %s" % (filespec, year, "Couldn't convert year tag to cccc, year tag ignored")
            filelog.write_warning(warningstring)
        else:
            yeardate = datetime.date(cccc, DEFAULTMONTH, DEFAULTDAY)
            ordinal = yeardate.toordinal()
    return ordinal

def splitworkvirtual(workstring):
    workstring = workstring.strip()
    worknumber = None
    if workstring != '':
        try:
            worknumberstring = re.split('\D', workstring)[0]
            if worknumberstring != '' and workstring[len(worknumberstring):len(worknumberstring)+1] == ',':
                workstring = workstring[len(worknumberstring)+1:]
                worknumber = int(worknumberstring)
        except ValueError:
            pass
        except AttributeError:
            pass
    if workstring == '':
        workstring = None
    return worknumber, workstring

work_sep = 'work='
virtual_sep = 'virtual='
wv_sep = '(%s|%s)' % (work_sep, virtual_sep)

'''
def translatealbumtype(albumtype):
    if albumtype == 'album':
        return 1
    elif albumtype == 'virtual':
        return 2
    elif albumtype == 'work':
        return 3

def translatestructuretype(structuretype):
    if structuretype == 'album_virtual':
        return 1
    elif structuretype == 'albumartist_album_virtual':
        return 2
    elif structuretype == 'artist_album_virtual':
        return 3
    elif structuretype == 'composer_album_virtual':
        return 4
    elif structuretype == 'album_work':
        return 1
    elif structuretype == 'albumartist_album_work':
        return 2
    elif structuretype == 'artist_album_work':
        return 3
    elif structuretype == 'composer_album_work':
        return 4
'''

def convertstructure(structurelist, lookup_name_dict):
    old_structures = []
    new_structures = []
    
    #            virtualstructurelist = [('_DEFAULT_VIRTUAL', '"%s" % (virtual)', 100), ('ALBUM_VIRTUAL', '"%s - %s" % (virtual, artist)', 101)]
    
    for name, structure, namevalue in structurelist:
        field_sep_pos = structure.rfind('(')
        field_string = structure[:field_sep_pos]
        fields = structure[field_sep_pos+1:]
        fields = fields[:fields.rfind(')')]
        fields = fields.split(',')
        old_fields = []
        new_fields = []
        for field in fields:
            field = field.strip()
            if field[0] == '_':
                field_transform = lookup_name_dict.get(field, None)
                if field_transform:        
                    field = field_transform
            # assume fieldname is first part of user defined field
            subfields = field.split('.')
            firstfield = subfields[0]
            restoffield = field[len(firstfield):]
            oldfield = convertfieldname(firstfield, 'old') + restoffield
            newfield = convertfieldname(firstfield, 'new') + restoffield
            old_fields.append(oldfield)
            new_fields.append(newfield)
        # recreate format strings
        fields = ','.join(old_fields)
        old_structures.append(('%s (%s)' % (field_string, fields), namevalue))
        fields = ','.join(new_fields)
        new_structures.append(('%s (%s)' % (field_string, fields), namevalue))
    return old_structures, new_structures

# convert field names
field_conversions = {
                    'work':'work',                          # dummy, not DB field
                    'virtual':'virtual',                    # dummy, not DB field
                    'id':'id', 
#                    'artist':'artistliststring', 
                    'artist':'artist', 
                    'album':'album', 
#                    'genre':'genreliststring', 
                    'genre':'genre', 
                    'tracknumber':'tracknumber', 
                    'year':'year', 
#                    'albumartist':'albumartistliststring', 
                    'albumartist':'albumartist', 
#                    'composer':'composerliststring', 
                    'composer':'composer', 
                    'created':'created', 
                    'lastmodified':'lastmodified', 
                    'inserted':'inserted'
                    }

def convertfieldname(fieldname, converttype):
    if fieldname in field_conversions:
        convertedfield = field_conversions[fieldname]
    else:
        convertedfield = 'notfound'

    if converttype == 'old':
        return "o_" + convertedfield
    else:
        return convertedfield

def check_target_database_exists(database):
    ''' 
        create database if it doesn't already exist
        if it exists, create tables if they don't exist
        return abs path
    '''
    create_database(database)

def create_database(database):
    db = sqlite3.connect(database)
    c = db.cursor()
    try:
        # master parameters
        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="params"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table params (key text,
                                              lastmodified integer, 
                                              lastscanstamp integer, 
                                              lastscanid integer, 
                                              use_albumartist text,
                                              show_duplicates text,
                                              album_identification text)
                      ''')
            c.execute('''insert into params values ('1', 0, 0, ' ', '', '', '')''')

        # work and virtual numbers
        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="wvlookup"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table wvlookup (wvtype text,
                                                wvnumber integer)
                      ''')

        # tracks - contain all detail from tags
        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="tracks"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table tracks (id text, 
                                              id2 text,
                                              duplicate integer,
                                              title text COLLATE NOCASE, 
                                              artist text COLLATE NOCASE, 
                                              artistfull text COLLATE NOCASE, 
                                              album text COLLATE NOCASE,
                                              genre text COLLATE NOCASE, 
                                              tracknumber integer,
                                              year integer,
                                              albumartist text COLLATE NOCASE, 
                                              albumartistfull text COLLATE NOCASE, 
                                              composer text COLLATE NOCASE, 
                                              composerfull text COLLATE NOCASE, 
                                              codec text,
                                              length integer, 
                                              size integer,
                                              created integer, 
                                              path text, 
                                              filename text,
                                              discnumber integer, 
                                              comment text, 
                                              folderart text,
                                              trackart text,
                                              bitrate integer, 
                                              samplerate integer, 
                                              bitspersample integer,
                                              channels integer, 
                                              mime text,
                                              lastmodified integer, 
                                              folderartid integer,
                                              trackartid integer,
                                              inserted integer,
                                              lastplayed integer,
                                              playcount integer,
                                              lastscanned integer,
                                              titlesort text COLLATE NOCASE,
                                              albumsort text COLLATE NOCASE)
                      ''')
            c.execute('''create unique index inxTracks on tracks (title, album, artist, tracknumber)''')
            c.execute('''create unique index inxTrackId on tracks (id)''')
            c.execute('''create index inxTrackId2 on tracks (id2)''')
            c.execute('''create index inxTrackDuplicates on tracks (duplicate)''')
            c.execute('''create index inxTrackTitles on tracks (title)''')
            c.execute('''create index inxTrackAlbums on tracks (album)''')
            c.execute('''create index inxTrackAlbumDups on tracks (album, duplicate)''')
            c.execute('''create index inxTrackAlbumDiscTrackTitles on tracks (album, discnumber, tracknumber, title)''')
            c.execute('''create index inxTrackDiscTrackTitles on tracks (discnumber, tracknumber, title)''')
            c.execute('''create index inxTrackArtists on tracks (artist)''')
            c.execute('''create index inxTrackAlbumArtists on tracks (albumartist)''')
            c.execute('''create index inxTrackComposers on tracks (composer)''')
            c.execute('''create index inxTrackTitlesort on tracks (titlesort)''')
            c.execute('''create index inxTrackYears on tracks (year)''')
            c.execute('''create index inxTrackLastmodifieds on tracks (lastmodified)''')
            c.execute('''create index inxTrackInserteds on tracks (inserted)''')
            c.execute('''create index inxTrackTracknumber on tracks (tracknumber)''')
            c.execute('''create index inxTrackLastplayeds on tracks (lastplayed)''')
            c.execute('''create index inxTrackPlaycounts on tracks (playcount)''')
            c.execute('''create index inxTrackPathFilename on tracks (path, filename)''')
            c.execute('''create index inxTrackPlay on tracks (title, album, artist, length)''')

        # albums - one entry for each unique album/artist/albumartist combination from tracks list
        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="albums"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table albums (id integer primary key autoincrement, 
                                              albumlist text COLLATE NOCASE, 
                                              artistlist text COLLATE NOCASE,
                                              year integer,
                                              albumartistlist text COLLATE NOCASE, 
                                              duplicate integer,
                                              cover text,
                                              artid integer,
                                              inserted integer,
                                              composerlist text COLLATE NOCASE,
                                              tracknumbers text,
                                              created integer,
                                              lastmodified integer,
                                              albumtype integer, 
                                              lastplayed integer,
                                              playcount integer,
                                              albumsort text COLLATE NOCASE)
                      ''')
            c.execute('''create unique index inxAlbums on albums (albumlist, artistlist, albumartistlist, duplicate, albumtype)''')
            c.execute('''create unique index inxAlbumId on albums (id)''')
            c.execute('''create index inxAlbumAlbums on albums (albumlist)''')
            c.execute('''create index inxAlbumAlbumsort on albums (albumsort)''')
            c.execute('''create index inxAlbumArtists2 on albums (artistlist)''')
            c.execute('''create index inxAlbumAlbumartists on albums (albumartistlist)''')
            c.execute('''create index inxAlbumComposers on albums (composerlist)''')
            c.execute('''create index inxAlbumYears on albums (year)''')
            c.execute('''create index inxAlbumInserteds on albums (inserted)''')
            c.execute('''create index inxAlbumcreateds on albums (created)''')
            c.execute('''create index inxAlbumlastmodifieds on albums (lastmodified)''')
            c.execute('''create index inxAlbumLastPlayeds on albums (lastplayed)''')
            c.execute('''create index inxAlbumPlaycounts on albums (playcount)''')
            c.execute('''create index inxAlbumAlbumtype on albums (albumtype)''')
            c.execute('''create index inxAlbumTracknumbers on albums (tracknumbers)''')
            c.execute('''create index inxAlbumTracknumbers2 on albums (albumlist, tracknumbers, albumtype, duplicate)''')

            # seed autoincrement
            c.execute('''insert into albums values (300000000,'','','','','','','','','','','','','','','','')''')
            c.execute('''delete from albums where id=300000000''')

        # albumsonly - one entry for each unique album from tracks list
        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="albumsonly"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table albumsonly (id integer primary key autoincrement, 
                                                  albumlist text COLLATE NOCASE, 
                                                  artistlist text COLLATE NOCASE,
                                                  year integer,
                                                  albumartistlist text COLLATE NOCASE, 
                                                  duplicate integer,
                                                  cover text,
                                                  artid integer,
                                                  inserted integer,
                                                  composerlist text COLLATE NOCASE,
                                                  tracknumbers text,
                                                  created integer,
                                                  lastmodified integer,
                                                  albumtype integer, 
                                                  lastplayed integer,
                                                  playcount integer,
                                                  albumsort text COLLATE NOCASE,
                                                  separated integer)
                      ''')
            c.execute('''create unique index inxAlbumsonly on albumsonly (albumlist, artistlist, albumartistlist, duplicate, albumtype)''')
            c.execute('''create unique index inxAlbumsonlyId on albumsonly (id)''')
            c.execute('''create index inxAlbumsonlyshort on albumsonly (albumlist, duplicate, albumtype)''')
    
            # seed autoincrement
            c.execute('''insert into albumsonly values (350000000,'','','','','','','','','','','','','','','','','')''')
            c.execute('''delete from albumsonly where id=350000000''')

        # artist/albumartist/composer/genre lookups - to hold playcounts

        # artists - one entry for each unique artist from tracks list
        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="Artist"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table Artist (id integer primary key autoincrement,
                                              artist text COLLATE NOCASE,
                                              lastplayed integer,
                                              playcount integer)
                      ''')
            c.execute('''create unique index inxArtists on Artist (artist)''')
            c.execute('''create index inxArtistLastplayeds on Artist (lastplayed)''')
            c.execute('''create index inxArtistPlaycounts on Artist (playcount)''')

            # seed autoincrement
            c.execute('''insert into Artist values (100000000,'','','')''')
            c.execute('''delete from Artist where id=100000000''')

        # albumartists - one entry for each unique albumartist from tracks list
        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="Albumartist"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table Albumartist (id integer primary key autoincrement,
                                                   albumartist text COLLATE NOCASE, 
                                                   lastplayed integer,
                                                   playcount integer)
                      ''')
            c.execute('''create unique index inxAlbumartists on Albumartist (albumartist)''')
            c.execute('''create index inxAlbumartistLastplayeds on Albumartist (lastplayed)''')
            c.execute('''create index inxAlbumartistPlaycounts on Albumartist (playcount)''')

            # seed autoincrement
            c.execute('''insert into Albumartist values (200000000,'','','')''')
            c.execute('''delete from Albumartist where id=200000000''')

        # composers - one entry for each unique composer from tracks list
        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="Composer"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table Composer (id integer primary key autoincrement,
                                                composer text COLLATE NOCASE,
                                                lastplayed integer,
                                                playcount integer)
                      ''')
            c.execute('''create unique index inxComposers on Composer (composer)''')
            c.execute('''create index inxComposerLastplayeds on Composer (lastplayed)''')
            c.execute('''create index inxComposerPlaycounts on Composer (playcount)''')

            # seed autoincrement
            c.execute('''insert into Composer values (400000000,'','','')''')
            c.execute('''delete from Composer where id=400000000''')

        # genres - one entry for each unique genre from tracks list
        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="Genre"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table Genre (id integer primary key autoincrement,
                                             genre text COLLATE NOCASE,
                                             lastplayed integer,
                                             playcount integer)
                      ''')
            c.execute('''create unique index inxGenres on Genre (genre)''')
            c.execute('''create index inxGenreLastplayeds on Genre (lastplayed)''')
            c.execute('''create index inxGenrePlaycounts on Genre (playcount)''')
            
            # seed autoincrement
            c.execute('''insert into Genre values (500000000,'','','')''')
            c.execute('''delete from Genre where id=500000000''')

        # playlists
#        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="playlists"')
#        n, = c.fetchone()
#        if n == 0:
#            c.execute('''create table playlists (id integer primary key autoincrement,
#                                                 playlist text COLLATE NOCASE,
#                                                 path text)
#                      ''')
#            c.execute('''create unique index inxPlaylists on playlists (playlist)''')
#            c.execute('''create unique index inxPlaylistId on playlists (id)''')
#            # seed autoincrement
#            c.execute('''insert into playlists values (700000000,'','')''')
#            c.execute('''delete from playlists where id=700000000''')
            
        # multi entry fields lookups - genre/artist level
        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="GenreArtist"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table GenreArtist (genre text COLLATE NOCASE,
                                                   artist text COLLATE NOCASE, 
                                                   lastplayed integer, 
                                                   playcount integer)
                      ''')
            c.execute('''create unique index inxGenreArtist on GenreArtist (genre, artist)''')
            c.execute('''create index inxGenreArtistLastplayed on GenreArtist (lastplayed)''')
            c.execute('''create index inxGenreArtistPlaycount on GenreArtist (playcount)''')

        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="GenreAlbumartist"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table GenreAlbumartist (genre text COLLATE NOCASE, 
                                                        albumartist text COLLATE NOCASE, 
                                                        lastplayed integer, 
                                                        playcount integer)
                      ''')
            c.execute('''create unique index inxGenreAlbumartist on GenreAlbumartist (genre, albumartist)''')
            c.execute('''create index inxGenreAlbumartistLastplayed on GenreAlbumartist (lastplayed)''')
            c.execute('''create index inxGenreAlbumartistPlaycount on GenreAlbumartist (playcount)''')

        # multi entry fields lookups - composer and artist/album level
        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="GenreArtistAlbum"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table GenreArtistAlbum (album_id integer, 
                                                        genre text COLLATE NOCASE, 
                                                        artist text COLLATE NOCASE, 
                                                        album text COLLATE NOCASE, 
                                                        duplicate integer, 
                                                        albumtype integer,
                                                        artistsort text COLLATE NOCASE, 
                                                        lastplayed integer, 
                                                        playcount integer)
                      ''')
            c.execute('''create unique index inxGenreArtistAlbum on GenreArtistAlbum (album_id, genre, artist, album, duplicate, albumtype, artistsort)''')
            c.execute('''create index inxGenreArtistAlbumGenreArtist on GenreArtistAlbum (genre, artist, album, albumtype)''')
            c.execute('''create index inxGenreArtistAlbumArtist on GenreArtistAlbum (artist)''')
            c.execute('''create index inxGenreArtistAlbumArtistsort on GenreArtistAlbum (artistsort)''')
            c.execute('''create index inxGenreArtistAlbumLastplayed on GenreArtistAlbum (lastplayed)''')
            c.execute('''create index inxGenreArtistAlbumPlaycount on GenreArtistAlbum (playcount)''')

        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="GenreAlbumartistAlbum"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table GenreAlbumartistAlbum (album_id integer, 
                                                             genre text COLLATE NOCASE, 
                                                             albumartist text COLLATE NOCASE, 
                                                             album text COLLATE NOCASE, 
                                                             duplicate integer, 
                                                             albumtype integer,
                                                             albumartistsort text COLLATE NOCASE, 
                                                             lastplayed integer, 
                                                             playcount integer)
                      ''')
            c.execute('''create unique index inxGenreAlbumartistAlbum on GenreAlbumartistAlbum (album_id, genre, albumartist, album, duplicate, albumtype, albumartistsort)''')
            c.execute('''create index inxGenreAlbumartistAlbumGenreAlbumartist on GenreAlbumartistAlbum (genre, albumartist, album, albumtype)''')
            c.execute('''create index inxGenreAlbumartistAlbumAlbumartist on GenreAlbumartistAlbum (albumartist)''')
            c.execute('''create index inxGenreAlbumartistAlbumAlbumartistsort on GenreAlbumartistAlbum (albumartistsort)''')
            c.execute('''create index inxGenreAlbumartistAlbumLastplayed on GenreAlbumartistAlbum (lastplayed)''')
            c.execute('''create index inxGenreAlbumartistAlbumPlaycount on GenreAlbumartistAlbum (playcount)''')

        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="ArtistAlbum"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table ArtistAlbum (album_id integer, 
                                                   artist text COLLATE NOCASE, 
                                                   album text COLLATE NOCASE, 
                                                   duplicate integer, 
                                                   albumtype integer,
                                                   artistsort text COLLATE NOCASE, 
                                                   lastplayed integer, 
                                                   playcount integer)
                      ''')
            c.execute('''create unique index inxArtistAlbum on ArtistAlbum (album_id, artist, album, duplicate, albumtype, artistsort)''')
            c.execute('''create index inxArtistAlbumArtist on ArtistAlbum (artist)''')
            c.execute('''create index inxArtistAlbumArtistsort on ArtistAlbum (artistsort)''')
            c.execute('''create index inxArtistAlbumArtistType on ArtistAlbum (artist, albumtype)''')
            c.execute('''create index inxArtistAlbumLastplayed on ArtistAlbum (lastplayed)''')
            c.execute('''create index inxArtistAlbumPlaycount on ArtistAlbum (playcount)''')

        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="AlbumartistAlbum"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table AlbumartistAlbum (album_id integer, 
                                                        albumartist text COLLATE NOCASE, 
                                                        album text COLLATE NOCASE, 
                                                        duplicate integer, 
                                                        albumtype integer,
                                                        albumartistsort text COLLATE NOCASE, 
                                                        lastplayed integer, 
                                                        playcount integer)
                      ''')
            c.execute('''create unique index inxAlbumartistAlbum on AlbumartistAlbum (album_id, albumartist, album, duplicate, albumtype, albumartistsort)''')
            c.execute('''create index inxAlbumartistAlbumAlbumartist on AlbumartistAlbum (albumartist)''')
            c.execute('''create index inxAlbumartistAlbumAlbumartistsort on AlbumartistAlbum (albumartistsort)''')
            c.execute('''create index inxAlbumartistAlbumAlbumartistType on AlbumartistAlbum (albumartist, albumtype)''')
            c.execute('''create index inxAlbumartistAlbumLastplayed on AlbumartistAlbum (lastplayed)''')
            c.execute('''create index inxAlbumartistAlbumPlaycount on AlbumartistAlbum (playcount)''')

        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="ComposerAlbum"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table ComposerAlbum (album_id integer, 
                                                     composer text COLLATE NOCASE, 
                                                     album text COLLATE NOCASE, 
                                                     duplicate integer, 
                                                     albumtype integer,
                                                     composersort text COLLATE NOCASE, 
                                                     lastplayed integer, 
                                                     playcount integer)
                      ''')
            c.execute('''create unique index inxComposerAlbum on ComposerAlbum (album_id, composer, album, duplicate, albumtype, composersort)''')
            c.execute('''create index inxComposerAlbumComposer on ComposerAlbum (composer)''')
            c.execute('''create index inxComposerAlbumComposersort on ComposerAlbum (composersort)''')
            c.execute('''create index inxComposerAlbumComposerType on ComposerAlbum (composer, albumtype)''')
            c.execute('''create index inxComposerAlbumAlbum on ComposerAlbum (album)''')
            c.execute('''create index inxComposerAlbumLastplayed on ComposerAlbum (lastplayed)''')
            c.execute('''create index inxComposerAlbumPlaycount on ComposerAlbum (playcount)''')

        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="ArtistAlbumsonly"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table ArtistAlbumsonly (album_id integer, 
                                                        album text COLLATE NOCASE, 
                                                        artist text,
                                                        duplicate integer, 
                                                        albumtype integer,
                                                        albumsort text COLLATE NOCASE, 
                                                        lastplayed integer, 
                                                        playcount integer)
                      ''')
            c.execute('''create unique index inxArtistAlbumsonly on ArtistAlbumsonly (album_id, album, duplicate, albumtype, albumsort)''')
            c.execute('''create index inxArtistAlbumsonlyAlbumsort on ArtistAlbumsonly (albumsort)''')
            c.execute('''create index inxArtistAlbumsonlyAlbumType on ArtistAlbumsonly (album, albumtype)''')
            c.execute('''create index inxArtistAlbumsonlyLastplayed on ArtistAlbumsonly (lastplayed)''')
            c.execute('''create index inxArtistAlbumsonlyPlaycount on ArtistAlbumsonly (playcount)''')

        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="AlbumartistAlbumsonly"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table AlbumartistAlbumsonly (album_id integer, 
                                                             album text COLLATE NOCASE, 
                                                             albumartist text,
                                                             duplicate integer, 
                                                             albumtype integer,
                                                             albumsort text COLLATE NOCASE, 
                                                             lastplayed integer, 
                                                             playcount integer)
                      ''')
            c.execute('''create unique index inxAlbumartistAlbumsonly on AlbumartistAlbumsonly (album_id, album, duplicate, albumtype, albumsort)''')
            c.execute('''create index inxAlbumartistAlbumsonlyAlbumsort on AlbumartistAlbumsonly (albumsort)''')
            c.execute('''create index inxAlbumartistAlbumsonlyAlbumType on AlbumartistAlbumsonly (album, albumtype)''')
            c.execute('''create index inxAlbumartistAlbumsonlyLastplayed on AlbumartistAlbumsonly (lastplayed)''')
            c.execute('''create index inxAlbumartistAlbumsonlyPlaycount on AlbumartistAlbumsonly (playcount)''')

        # multi entry fields lookups - album/track level
        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="GenreArtistAlbumTrack"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table GenreArtistAlbumTrack (track_id integer, 
                                                             genre text COLLATE NOCASE, 
                                                             artist text COLLATE NOCASE, 
                                                             album text COLLATE NOCASE, 
                                                             album_id integer,
                                                             duplicate integer, 
                                                             albumtype integer)
                      ''')
            c.execute('''create unique index inxGenreArtistAlbumTrack on GenreArtistAlbumTrack (track_id, genre, artist, album, duplicate, albumtype)''')
            c.execute('''create index inxGenreArtistAlbumTrackGenreArtistAlbum on GenreArtistAlbumTrack (genre, artist, album, albumtype)''')
            c.execute('''create index inxGenreArtistAlbumTrackGenreArtistAlbumDup on GenreArtistAlbumTrack (genre, artist, album, duplicate)''')
            c.execute('''create index inxGenreArtistAlbumTrackGenreArtistAlbumIdDup on GenreArtistAlbumTrack (genre, artist, album_id, duplicate)''')

        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="GenreAlbumartistAlbumTrack"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table GenreAlbumartistAlbumTrack (track_id integer, 
                                                                  genre text COLLATE NOCASE, 
                                                                  albumartist text COLLATE NOCASE, 
                                                                  album text COLLATE NOCASE, 
                                                                  album_id integer,
                                                                  duplicate integer, 
                                                                  albumtype integer)
                      ''')
            c.execute('''create unique index inxGenreAlbumartistAlbumTrack on GenreAlbumartistAlbumTrack (track_id, genre, albumartist, album, duplicate, albumtype)''')
            c.execute('''create index inxGenreAlbumartistAlbumTrackGenreAlbumArtistAlbum on GenreAlbumartistAlbumTrack (genre, albumartist, album, albumtype)''')
            c.execute('''create index inxGenreAlbumartistAlbumTrackGenreAlbumArtistAlbumDup on GenreAlbumartistAlbumTrack (genre, albumartist, album, duplicate)''')
            c.execute('''create index inxGenreAlbumartistAlbumTrackGenreAlbumArtistAlbumIdDup on GenreAlbumartistAlbumTrack (genre, albumartist, album_id, duplicate)''')

        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="ArtistAlbumTrack"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table ArtistAlbumTrack (track_id integer, 
                                                        artist text COLLATE NOCASE, 
                                                        album text COLLATE NOCASE, 
                                                        album_id integer,
                                                        duplicate integer, 
                                                        albumtype integer)
                      ''')
            c.execute('''create unique index inxArtistAlbumTrack on ArtistAlbumTrack (track_id, artist, album, duplicate, albumtype)''')
            c.execute('''create index inxArtistAlbumTrackArtistAlbum on ArtistAlbumTrack (artist, album, albumtype)''')
            c.execute('''create index inxArtistAlbumTrackArtistAlbumDup on ArtistAlbumTrack (artist, album, duplicate, albumtype)''')
            c.execute('''create index inxArtistAlbumTrackArtistAlbumIdDup on ArtistAlbumTrack (artist, album_id, duplicate, albumtype)''')

        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="AlbumartistAlbumTrack"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table AlbumartistAlbumTrack (track_id integer, 
                                                             albumartist text COLLATE NOCASE, 
                                                             album text COLLATE NOCASE, 
                                                             album_id integer,
                                                             duplicate integer, 
                                                             albumtype integer)
                      ''')
            c.execute('''create unique index inxAlbumArtistAlbumTrack on AlbumartistAlbumTrack (track_id, albumartist, album, duplicate, albumtype)''')
            c.execute('''create index inxAlbumArtistAlbumTrackAlbumArtistAlbum on AlbumartistAlbumTrack (albumartist, album, albumtype)''')
            c.execute('''create index inxAlbumArtistAlbumTrackAlbumArtistAlbumDup on AlbumartistAlbumTrack (albumartist, album, duplicate, albumtype)''')
            c.execute('''create index inxAlbumArtistAlbumTrackAlbumArtistAlbumIdDup on AlbumartistAlbumTrack (albumartist, album_id, duplicate, albumtype)''')

        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="ComposerAlbumTrack"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table ComposerAlbumTrack (track_id integer, 
                                                          composer text COLLATE NOCASE, 
                                                          album text COLLATE NOCASE, 
                                                          album_id integer,
                                                          duplicate integer, 
                                                          albumtype integer)
                      ''')
            c.execute('''create unique index inxComposerAlbumTrack on ComposerAlbumTrack (track_id, composer, album, duplicate, albumtype)''')
            c.execute('''create index inxComposerAlbumTrackComposerAlbum on ComposerAlbumTrack (composer, album, albumtype)''')
            c.execute('''create index inxComposerAlbumTrackComposerAlbumDup on ComposerAlbumTrack (composer, album, duplicate, albumtype)''')
            c.execute('''create index inxComposerAlbumTrackComposerAlbumIdDup on ComposerAlbumTrack (composer, album_id, duplicate, albumtype)''')

        # work/virtual track number lookup
        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="TrackNumbers"')
        n, = c.fetchone()
        if n == 0:
            # TODO: check these indexes
            c.execute('''create table TrackNumbers (track_id integer, 
                                                    genre text COLLATE NOCASE, 
                                                    artist text COLLATE NOCASE, 
                                                    albumartist text COLLATE NOCASE, 
                                                    album text COLLATE NOCASE, 
                                                    dummyalbum text COLLATE NOCASE, 
                                                    composer text COLLATE NOCASE, 
                                                    duplicate integer, 
                                                    albumtype integer, 
                                                    tracknumber integer,
                                                    coverart text,
                                                    coverartid integer)
                      ''')
            c.execute('''create unique index inxTrackNumbers on TrackNumbers (track_id, genre, artist, albumartist, album, dummyalbum, composer, duplicate, albumtype, tracknumber, coverart, coverartid)''')
            c.execute('''create index inxTrackNumbersGenreArtist on TrackNumbers (genre, artist, dummyalbum, duplicate, albumtype)''')
            c.execute('''create index inxTrackNumbersGenreAlbumartist on TrackNumbers (genre, albumartist, dummyalbum, duplicate, albumtype)''')
            c.execute('''create index inxTrackNumbersArtist on TrackNumbers (artist, dummyalbum, duplicate, albumtype)''')
            c.execute('''create index inxTrackNumbersAlbumartist on TrackNumbers (albumartist, dummyalbum, duplicate, albumtype)''')
            c.execute('''create index inxTrackNumbersComposer on TrackNumbers (composer, dummyalbum, duplicate, albumtype)''')

    except sqlite3.Error, e:
        errorstring = "Error creating database: %s, %s" % (database, e)
        filelog.write_error(errorstring)
    db.commit()
    c.close()

def empty_database(database):

    # check whether there are any track tables (check for last table in delete list below)
    db = sqlite3.connect(database)
    c = db.cursor()
    c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="TrackNumbers"')
    n, = c.fetchone()
    if n != 0:
        logstring = "Deleting tracks data"
        filelog.write_log(logstring)
        try:
            c.execute('''drop table if exists params''')
            c.execute('''drop table if exists wvlookup''')
            c.execute('''drop table if exists tracks''')
            c.execute('''drop table if exists albums''')
            c.execute('''drop table if exists albumsonly''')

            # to be removed from this list - are tables from an old schema
            c.execute('''drop table if exists artists''')
            c.execute('''drop table if exists albumartists''')
            c.execute('''drop table if exists composers''')
            c.execute('''drop table if exists genres''')

            c.execute('''drop table if exists Artist''')
            c.execute('''drop table if exists Albumartist''')
            c.execute('''drop table if exists Composer''')
            c.execute('''drop table if exists Genre''')
            c.execute('''drop table if exists GenreArtist''')
            c.execute('''drop table if exists GenreAlbumartist''')
            c.execute('''drop table if exists GenreArtistAlbum''')
            c.execute('''drop table if exists GenreAlbumartistAlbum''')
            c.execute('''drop table if exists ArtistAlbum''')
            c.execute('''drop table if exists AlbumartistAlbum''')
            c.execute('''drop table if exists ComposerAlbum''')
            c.execute('''drop table if exists ArtistAlbumsonly''')
            c.execute('''drop table if exists AlbumartistAlbumsonly''')
            c.execute('''drop table if exists GenreArtistAlbumTrack''')
            c.execute('''drop table if exists GenreAlbumartistAlbumTrack''')
            c.execute('''drop table if exists ArtistAlbumTrack''')
            c.execute('''drop table if exists AlbumartistAlbumTrack''')
            c.execute('''drop table if exists ComposerAlbumTrack''')
            c.execute('''drop table if exists TrackNumbers''')
        except sqlite3.Error, e:
            errorstring = "Error dropping table: %s, %s" % (table, e)
            filelog.write_error(errorstring)
        db.commit()
        c.close()
        logstring = "Tracks data deleted"
        filelog.write_log(logstring)

def process_command_line(argv):
    """
        Return a 2-tuple: (settings object, args list).
        `argv` is a list of arguments, or `None` for ``sys.argv[1:]``.
    """
    if argv is None:
        argv = sys.argv[1:]

    # initialize parser object
    parser = optparse.OptionParser(
        formatter=optparse.TitledHelpFormatter(width=78),
        add_help_option=None)

    # options
    parser.add_option("-s", "--tagdatabase", dest="tagdatabase", type="string", 
                      help="read tags from source DATABASE", action="store",
                      metavar="TAGDATABASE")
    parser.add_option("-d", "--trackdatabase", dest="trackdatabase", type="string", 
                      help="write tags to destination DATABASE", action="store",
                      metavar="TRACKDATABASE")
    parser.add_option("-t", "--the", dest="the_processing", type="string", 
                      help="how to process 'the' before artist name (before/after(default)/remove)", 
                      action="store", default='remove',
                      metavar="THE")
    parser.add_option("-c", "--count", dest="scancount", type="int", 
                      help="process 'count' number of scans", action="store",
                      metavar="COUNT")
    parser.add_option("-r", "--regenerate",
                      action="store_true", dest="regenerate", default=False,
                      help="regenerate database")
    parser.add_option("-v", "--verbose",
                      action="store_true", dest="verbose", default=False,
                      help="print verbose status messages to stdout")
    parser.add_option("-q", "--quiet",
                      action="store_true", dest="quiet", default=False,
                      help="don't print status messages to stdout")
    parser.add_option('-h', '--help', action='help',
                      help='Show this help message and exit.')
    settings, args = parser.parse_args(argv)
    return settings, args

def main(argv=None):
    options, args = process_command_line(argv)
    filelog.set_log_type(options.quiet, options.verbose)
    filelog.open_log_files()
    if len(args) != 0 or not options.tagdatabase or not options.trackdatabase: 
        print "Usage: %s [options]" % sys.argv[0]
    else:
        tagdatabase = options.tagdatabase
        trackdatabase = options.trackdatabase
        if not os.path.isabs(tagdatabase):
            tagdatabase = os.path.join(os.getcwd(), tagdatabase)
        if not os.path.isabs(trackdatabase):
            trackdatabase = os.path.join(os.getcwd(), trackdatabase)
        if options.regenerate:
            empty_database(trackdatabase)
        check_target_database_exists(trackdatabase)
        process_tags(args, options, tagdatabase, trackdatabase)
    filelog.close_log_files()
    return 0

if __name__ == "__main__":
    status = main()
    sys.exit(status)

