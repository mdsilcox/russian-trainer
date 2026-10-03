# Natural Russian voices

The app can speak with Microsoft's natural Russian voices (Svetlana, Dariya and Dmitry) in any browser. It uses Azure Speech for this. Without a key it keeps using your browser's own voices, so nothing breaks if you skip this.

Azure's free tier gives you 500,000 characters of speech a month. Every line is saved on your computer after it is first spoken, so replays cost nothing.

## Setup

1. Create a free Azure account at https://azure.microsoft.com/free (a card is needed to sign up, but nothing is charged on the free tier).
2. In the Azure portal, create a "Speech" resource (search for "Speech service"). Choose the free **F0** pricing tier and any region near you.
3. Open the resource and go to "Keys and Endpoint". Copy **Key 1** and the **Location/Region** (for example `westeurope`).
4. Set two Windows user environment variables: open Start, search "Edit environment variables for your account", and add
   - `AZURE_SPEECH_KEY` = the key you copied
   - `AZURE_SPEECH_REGION` = the region, for example `westeurope`
5. Close the app completely and start it again. Settings should now say "Natural voices on". Pick a voice there and press "Play a sample".

## Good to know

- The text of the lines you play is sent to Microsoft to make the audio. Nothing else is sent.
- The key stays on your computer in your environment variables. The app never shows or logs it.
- If the key is wrong, or the free allowance for the month is used up, the app speaks with your browser's voice instead.
- Saved audio lives in the `tts` folder inside the app's data folder. It is safe to delete.
