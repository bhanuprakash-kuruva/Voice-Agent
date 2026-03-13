import pyttsx3
import os


def speak(text, filename="response.wav"):

    print("\n🔊 Generating speech audio...\n")

    engine = pyttsx3.init()
    engine.setProperty("rate", 170)

    try:
        engine.save_to_file(text, filename)
        engine.runAndWait()
    finally:
        engine.stop()

    print(f"Audio saved as: {filename}")

    choice = input("Do you want to listen to the response? (y/n): ").lower()

    if choice == "y":
        print("\n🔊 Playing response...\n")
        os.startfile(filename)