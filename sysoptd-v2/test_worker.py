import sys, os, tempfile, stat, subprocess

# Use relative paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, 'lib'))

from loader import assemble_to_memfd

data_dir = os.path.join(SCRIPT_DIR, 'data')
fd = assemble_to_memfd(data_dir, label="test-worker")
size = os.lseek(fd, 0, os.SEEK_END)
os.lseek(fd, 0, os.SEEK_SET)
data = os.read(fd, size)
os.close(fd)
tmp = tempfile.NamedTemporaryFile(delete=False, prefix='.test_', dir='/tmp')
tmp.write(data)
tmp.close()
os.chmod(tmp.name, 0o700)
r = subprocess.run([tmp.name, '--help'], capture_output=True, timeout=5)
print('OUT:', r.stdout[:300])
print('ERR:', r.stderr[:300])
print('CODE:', r.returncode)
os.unlink(tmp.name)

# Deployment ID: b4003f8d72f7f514
