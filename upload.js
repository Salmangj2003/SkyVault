function uploadFiles(files){

const progressBox = document.getElementById("progressBox")

progressBox.innerHTML = `
<div class="progress">
<div class="progress-bar" id="bar"></div>
</div>
`

const xhr = new XMLHttpRequest()
const fd = new FormData()

fd.append("file", files[0])

xhr.upload.addEventListener("progress", e => {

if(e.lengthComputable){

let percent = (e.loaded / e.total) * 100
document.getElementById("bar").style.width = percent + "%"

}

})

xhr.onload = () => {
location.reload()
}

xhr.open("POST","/upload")
xhr.send(fd)

}