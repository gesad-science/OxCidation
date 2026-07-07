use proconio::input;

fn main() {
    input!{
        n: usize,
        x: usize,
        m: usize,
    }
    
    let mut to = vec![100001; m];
    let l = {
        let mut a = x;
        while to[a] == 100001 {
            let b = a * a % m;
            to[a] = b;
            a = b;
        }
        a
    };
    
    let mut ans = 0;
    let mut a = x;
    if n <= 300000 {
        for _ in 0..n {
            ans += a;
            a = a * a % m;
        }
    }
    else {
        let mut n = n;
        while a != l {
            ans += a;
            a = a * a % m;
            n -= 1;
        }
        // a = a * a % m;
        // n -= 1;
        let mut cycle = 0;
        let mut sum = 0;
        loop {
            sum += a;
            a = a * a % m;
            cycle += 1;
            if a == l {
                break;
            }
        }
        let loops = n/cycle;
        ans += sum * loops;
        n -= loops * cycle;
        for _ in 0..n {
            ans += a;
            a = a * a % m;
        }
    }
    println!("{}", ans);
}
