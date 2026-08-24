#!/bin/bash

# Activate the virtual environment
if [[ "$OSTYPE" == "darwin"* ]] || [[ "$OSTYPE" == "linux-gnu"* ]]; then
    # macOS or Linux
    source venv/bin/activate
elif [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]]; then
    # Windows
    source venv/Scripts/activate
else
    echo "Unsupported OS. Please activate the virtual environment manually."
    exit 1
fi

# Install dependencies
pip install -r requirements.txt

# Verify installation
python -c "import agents; print(f'OpenAI Agents SDK installed successfully!')"

echo "Setup complete! You can now run the example scripts." 