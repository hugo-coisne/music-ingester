"""Regression tests for library."""

from music_ingest import history, library

from tests.support import TemporaryTest, track


class DuplicateTests(TemporaryTest):
    def test_recording_id_matches_without_duration_but_conflicts_block_text_match(self):
        item = self.item()
        item['recording_mbid'] = '526bd613-fddd-4bd6-9137-ab709ac74cab'
        item['isrc'] = 'USABC1200001'
        index = {}
        library.add_to_library_index(index, item)
        candidate = dict(track(title='Different title', duration=None), recording_mbid=item['recording_mbid'])
        self.assertIsNotNone(library.find_existing_track(candidate, index))
        candidate = dict(track(), recording_mbid='a6081bc1-2a76-4984-b21f-38bc3dcca3a5')
        self.assertIsNone(library.find_existing_track(candidate, index))
        candidate = dict(track(), isrc='USABC1200002')
        self.assertIsNone(library.find_existing_track(candidate, index))

    def test_artist_is_not_substring(self):
        self.assertFalse(library.artists_match(track(), self.item('Air Supply')))
        self.assertTrue(library.artists_match(track(artist='Beyoncé'), self.item('Beyonce')))

    def test_duplicate_requires_title_artist_duration_and_live_path(self):
        item = self.item()
        index = {}
        library.add_to_library_index(index, item)
        self.assertIsNotNone(library.find_existing_track(track(title='Song (feat. Guest)'), index))
        for value in [track(title='Other'), track(artist='Other'), track(duration=9),
                      track(duration=None), track(duration='bad')]:
            self.assertIsNone(library.find_existing_track(value, index))
        item['path'].unlink()
        self.assertIsNone(library.find_existing_track(track(), index))

    def test_directory_is_not_completed_import(self):
        db = history.connect_db(self.config.db_path)
        self.addCleanup(db.close)
        history.mark_pending(db, 'video1', 'Air', 'Song')
        history.mark_done(db, 'video1', self.root)
        self.assertFalse(history.existing_import(db, 'video1'))

