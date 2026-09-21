"""Regression tests for library."""

from music_ingest import history, library

from tests.support import TemporaryTest, track


class DuplicateTests(TemporaryTest):
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

