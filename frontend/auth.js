// Set login status (call this after successful login)
function setLoginStatus(isLoggedIn) {
    if (isLoggedIn) {
        localStorage.setItem('isLoggedIn', 'true');
    } else {
        localStorage.removeItem('isLoggedIn');
    }
}

// Check login status
function isUserLoggedIn() {
    return localStorage.getItem('isLoggedIn') === 'true';
}

