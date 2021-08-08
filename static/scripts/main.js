async function postData(url = '', data = {}) {
  // Default options are marked with *
  const response = await fetch(url, {
    method: 'POST', // *GET, POST, PUT, DELETE, etc.
    mode: 'cors', // no-cors, *cors, same-origin
    credentials: 'same-origin', // include, *same-origin, omit
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(data) // body data type must match "Content-Type" header
  });
  return response.json(); // parses JSON response into native JavaScript objects
}

document.getElementById('newsletter-form').addEventListener('submit', (e) => {
  e.preventDefault();
  toastr.options = {
    "progressBar": true,
  }
  postData('add_newsletter', {email: e.target[0].value})
    .then(response => {
      if (response.status === 'ok') {
        e.target[0].value = '';
        toastr['success']("Udało ci się dołączyć do newslettera!")
      } else if (response.status === 'invalid_email_format') {
        e.target[0].value = '';
        toastr['error']("Adres email ma błędny format")
      } else if (response.status === 'email_already_exists') {
        e.target[0].value = '';
        toastr['error']("Adres email należy już do newslettera")
      }
    })
})