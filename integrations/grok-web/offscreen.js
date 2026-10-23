const audio = document.getElementById('sound');
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (sender.id !== chrome.runtime.id || message?.target !== 'offscreen' || message.type !== 'play') return;
  audio.pause();
  audio.src = message.source;
  audio.currentTime = 0;
  audio.play().then(() => reply({ok: true}), () => reply({ok: false}));
  return true;
});
