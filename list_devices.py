import sounddevice as sd
for i, d in enumerate(sd.query_devices()):
    mark = ">>>" if d["max_input_channels"] > 0 else "   "
    print(f"{mark} [{i}] {d['name']}  in={d['max_input_channels']} out={d['max_output_channels']}")
print()
print("Default input:", sd.query_devices(kind='input')['name'])
