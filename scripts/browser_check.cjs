// Isolated real Edge video playback -> system loopback. No fake audio device.
const { chromium } = require(process.env.PLAYWRIGHT_PACKAGE || 'playwright');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

(async () => {
  const proc = spawn(path.resolve('.venv/Scripts/python.exe'), ['-m','scripts.loopback_check','--seconds','55','--manual','--output','artifacts/edge-video-report.json'], {
    env:{...process.env,PYTHONIOENCODING:'utf-8'},stdio:['ignore','pipe','pipe']
  });
  let output='';
  const finished = new Promise((resolve,reject)=>{proc.on('exit',code=>code===0?resolve():reject(Error(`Capture exit ${code}`)));});
  proc.stdout.on('data',b=>{output+=b.toString();});
  proc.stderr.on('data',b=>{output+=b.toString();});
  const browser=await chromium.launch({channel:'msedge',headless:true,
    ignoreDefaultArgs:['--mute-audio'],args:['--autoplay-policy=no-user-gesture-required']});
  try {
    const page=await browser.newPage({viewport:{width:1280,height:900}});
    await page.goto(pathToFileURL(path.resolve('artifacts/player.html')).href);
    // Wait until real loopback is ready, with a bounded startup deadline.
    for(let i=0;i<100 && !output.includes('回环捕获中');i++) await new Promise(r=>setTimeout(r,100));
    if(!output.includes('回环捕获中')) throw Error('Loopback did not start');
    const playback=[];
    for(const language of ['english','chinese']) {
      await page.evaluate(async name=>{const v=document.querySelector('video');v.src=name+'.mp4';v.muted=false;v.volume=1;await v.play();},language);
      await page.waitForFunction(()=>document.querySelector('video').ended,{},{timeout:20000});
      playback.push(await page.evaluate(()=>{const v=document.querySelector('video');return {source:v.currentSrc,time:v.currentTime,duration:v.duration,muted:v.muted,ended:v.ended};}));
    }
    await page.screenshot({path:'artifacts/edge-video.png'});
    fs.writeFileSync('artifacts/edge-playback.json',JSON.stringify(playback,null,2));
    await finished;
  } finally {
    await browser.close();
    fs.writeFileSync('artifacts/edge-video-console.log',output);
  }
})().catch(e=>{console.error(e);process.exitCode=1;});
