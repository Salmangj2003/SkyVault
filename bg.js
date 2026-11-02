const canvas=document.getElementById("bg")
const ctx=canvas.getContext("2d")

canvas.width=window.innerWidth
canvas.height=window.innerHeight

let particles=[]

for(let i=0;i<140;i++){

particles.push({

x:Math.random()*canvas.width,
y:Math.random()*canvas.height,
vx:(Math.random()-0.5)*0.4,
vy:(Math.random()-0.5)*0.4

})

}

function draw(){

ctx.clearRect(0,0,canvas.width,canvas.height)

particles.forEach((p,i)=>{

p.x+=p.vx
p.y+=p.vy

if(p.x<0||p.x>canvas.width) p.vx*=-1
if(p.y<0||p.y>canvas.height) p.vy*=-1

ctx.beginPath()
ctx.arc(p.x,p.y,2,0,Math.PI*2)
ctx.fillStyle="#6366f1"
ctx.fill()

particles.forEach(p2=>{

let dist=Math.hypot(p.x-p2.x,p.y-p2.y)

if(dist<120){

ctx.beginPath()
ctx.moveTo(p.x,p.y)
ctx.lineTo(p2.x,p2.y)
ctx.strokeStyle="rgba(99,102,241,.15)"
ctx.stroke()

}

})

})

requestAnimationFrame(draw)

}

draw()