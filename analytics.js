let uploadChart
let userChart
let storageChart

document.addEventListener("DOMContentLoaded", loadAnalytics)

async function loadAnalytics(){

const res = await fetch("/api/analytics")
const data = await res.json()

const uploadLabels = data.uploads.map(x => x[0])
const uploadData = data.uploads.map(x => x[1])

const userLabels = data.growth.map(x => x[0])
const userData = data.growth.map(x => x[1])

createUploadChart(uploadLabels, uploadData)
createUserChart(userLabels, userData)
createStorageChart(data.storage)

}

/* Upload Chart */

function createUploadChart(labels,data){

if(uploadChart) uploadChart.destroy()

uploadChart = new Chart(
document.getElementById("uploadChart"),
{
type:"line",
data:{
labels:labels,
datasets:[{
label:"Uploads",
data:data,
borderWidth:3,
tension:.3
}]
},
options:{
responsive:true,
maintainAspectRatio:false
}
})

}

/* User Growth */

function createUserChart(labels,data){

if(userChart) userChart.destroy()

userChart = new Chart(
document.getElementById("userChart"),
{
type:"line",
data:{
labels:labels,
datasets:[{
label:"User Growth",
data:data,
borderWidth:3,
tension:.3
}]
},
options:{
responsive:true,
maintainAspectRatio:false
}
})

}

/* Storage */

function createStorageChart(storage){

if(storageChart) storageChart.destroy()

storageChart = new Chart(
document.getElementById("storageChart"),
{
type:"bar",
data:{
labels:["Storage Used"],
datasets:[{
label:"MB",
data:[storage],
borderWidth:2
}]
},
options:{
responsive:true,
maintainAspectRatio:false
}
})

}