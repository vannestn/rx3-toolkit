"""Execute persistence and exact-build refusal paths using host fixtures only."""
import pathlib
import subprocess
import tempfile
import unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
GUARD=ROOT/'mod/lib/volatile-guard.sh'
MODULE=ROOT/'mod/modules/position-diagnostic/module.sh'

class PositionSafetyTests(unittest.TestCase):
    def mount_check(self, text):
        with tempfile.TemporaryDirectory() as directory:
            mounts=pathlib.Path(directory)/'mounts';mounts.write_text(text)
            return subprocess.run(['sh','-c','. "$1"; volatile_mount_layout "$2"','test',str(GUARD),str(mounts)]).returncode

    def test_mounts_reject_persistent_ancestors_nested_targets_and_missing_root(self):
        good='rootfs / rootfs rw 0 0\nproc /proc proc rw 0 0\n'
        self.assertEqual(self.mount_check(good),0)
        self.assertEqual(self.mount_check(good+'tmpfs /tmp tmpfs rw 0 0\n'),0)
        for bad in ('/dev/flash /root ext4 rw 0 0\n','/dev/flash /root/pdj ext4 rw 0 0\n',
                    '/dev/flash /root/pdj/rbp ext4 rw 0 0\n','/dev/flash /tmp ext4 rw 0 0\n',
                    '/dev/flash /tmp/rx3-stems.log ext4 rw 0 0\n'):
            self.assertNotEqual(self.mount_check(good+bad),0,bad)
        for bad in ('','malformed\n','/dev/flash / ext4 rw 0 0\n','proc /proc proc rw 0 0\n'):
            self.assertNotEqual(self.mount_check(bad),0,bad)
        # Unrelated USB mounts are not modified by this guard.
        self.assertEqual(self.mount_check(good+'/dev/sda /media/usb1/A vfat rw 0 0\n'),0)

    def test_symlink_and_device_destinations_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=pathlib.Path(directory);(root/'root/pdj').mkdir(parents=True);(root/'tmp').mkdir()
            def check():
                return subprocess.run(['sh','-c','. "$1"; volatile_path_layout "$2"','test',str(GUARD),str(root)]).returncode
            self.assertEqual(check(),0)
            p=root/'root/pdj/rbp';p.symlink_to('/dev/null');self.assertNotEqual(check(),0);p.unlink()
            p=root/'tmp/rx3-performance.ready';p.symlink_to('/dev/null');self.assertNotEqual(check(),0);p.unlink()
            p.mkdir();self.assertNotEqual(check(),0);p.rmdir()
            p=root/'root/pdj';p.rmdir();p.symlink_to(root/'tmp');self.assertNotEqual(check(),0)

    def test_diagnostic_refuses_other_firmware_and_reinsertion_succeeds(self):
        with tempfile.TemporaryDirectory() as directory:
            core=pathlib.Path(directory)/'core.so';core.write_text('fixture')
            setup='''
module_begin() { :; }
register_prepare_hook() { :; }
module_disabled_by_switch() { return 1; }
say() { :; }
# 1 is the real API result when the running setting is already identical.
module_export() { echo exported; return 1; }
. "$1"
CORE_OBJECT=$2
ACCEPTED=$3
position_diagnostic_prepare
'''
            expected='cf309238491e73cdbdc1f08a09f7a3177e079068'
            for identity in ('','unknown','3513d34b7ff7ae7b29e3041c6f44116ff2741f90',expected):
                result=subprocess.run(['sh','-c',setup,'test',str(MODULE),str(core),identity],capture_output=True,text=True)
                self.assertEqual(result.returncode==0,identity==expected)
                self.assertEqual('exported' in result.stdout,identity==expected)

    def test_guard_runs_before_probe_and_module_loading(self):
        source=(ROOT/'mod/autoexec.sh').read_text()
        guard=source.index('volatile_mount_layout /proc/mounts')
        self.assertLess(guard,source.index('sh /mnt/iso/lib/safe-mode.sh'))
        self.assertLess(guard,source.index('load_module()'))
        self.assertIn('RUNTIME_STAGE_DIR=/root/pdj/.rx3-stage.$$',source)


class SnapshotSafetyTests(unittest.TestCase):
    def test_now_playing_interrupted_writer_does_not_spin_forever(self):
        from tests import test_framework as harness
        from tests.test_runtime_transitions import function
        source=ROOT/'mod/modules/now-playing/rx3_now_playing_feature.h'
        code=function(source,'now_playing_read_deck')
        harness.FrameworkTests.run_units(self,r"""
#define NOW_PLAYING_TITLE_UNITS 128u
struct now_playing_deck { volatile unsigned revision; uint8_t loaded; uint32_t track_id; uint16_t title[128]; };
static struct now_playing_deck now_playing_decks[2];
"""+code+r"""
int main(void) {
 struct now_playing_deck out={0};
 now_playing_decks[0].revision=1;
 assert(!now_playing_read_deck(0,&out));
 now_playing_decks[0].track_id=42;now_playing_decks[0].loaded=1;now_playing_decks[0].revision=2;
 assert(now_playing_read_deck(0,&out)&&out.track_id==42&&out.loaded);
 return 0;
}
""", [])
