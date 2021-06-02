# tm-testkit
A tool box for testing Tendermint

### Installation
It's recommended that you use a Python virtual environment to manage
dependencies for the `tm-testkit` tool.

```bash
git clone git@github.com:gitferry/tm-testkit.git
cd tm-testkit

# Create the virtual environment in a folder called "venv"
python3 -m venv venv

# Activate your Python virtual environment
source venv/bin/activate

# Install dependencies for tmtestnet (this will install Ansible, amongst other
# dependencies, into your virtual environment)
pip install -r requirements.txt