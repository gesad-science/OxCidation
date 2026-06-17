use std::io::{stdin, Read, StdinLock};
use std::str::FromStr;
use std::cmp;
use std::collections::BTreeSet;

struct Scanner<'a> {
    cin : StdinLock<'a>,
}

impl<'a> Scanner<'a> {
    fn new(cin : StdinLock<'a>) -> Scanner<'a> {
        Scanner { cin: cin }
    }

    fn read1<T: FromStr>(&mut self) -> Option<T> {
        let token = self.cin.by_ref().bytes().map(|c| c.unwrap() as char)
            .skip_while(|c| c.is_whitespace())
            .take_while(|c| !c.is_whitespace())
            .collect::<String>();
        token.parse::<T>().ok()
    }

    fn read<T: FromStr>(&mut self) -> T {
        self.read1().unwrap()
    }
}


fn into_code(name: &String, k: usize) -> Vec<char> {
    let boin : BTreeSet<char> = "aeiou".chars().collect();
    let mut cs = (*name).chars().collect::<Vec<char>>();
    let mut ret = Vec::<char>::new();
    ret.push(*(cs.first().unwrap()));
    for wd in cs.as_slice().windows(2) {
        let (prev, now) = (wd[0], wd[1]);
        if ret.len() == k {break;}
        if boin.contains(&prev) {
            ret.push(now);
        }
    }
    ret
}


fn main(){
	let cin = stdin();
	let cin = cin.lock();
	let mut sc = Scanner::new(cin);
    loop{
        let n : usize = sc.read();
        if n == 0 { break; }
        let mut names = Vec::new();
        let mut msize = 0;
        for _ in 0..n {
            names.push(sc.read::<String>());
            if msize < names.last().unwrap().len(){
                msize = names.last().unwrap().len();
            }
            //println!("{}", names.last().unwrap());
        }
        //println!("s:{}", msize);
        let mut ended = false;
        for k in 1..msize {
            let mut nms = BTreeSet::new();
            for name in &names {
                if !nms.insert(into_code(name, k)) {
                    break;
                }
            }
            if nms.len() == n {
                //for i in nms {
                    //println!("{:?}", i);
                //}
                println!("{}", k);
                ended = true;
                break;
            }
        }
        if !ended {
            let mut nms = BTreeSet::new();
            for name in &names {
                if !nms.insert(into_code(name, msize)) {
                    break;
                }
            }
            if nms.len() == n {
                //for i in nms {
                    //println!("{:?}", i);
                //}
                println!("{}", msize);
            } else {
                println!("-1");
            }
        }
    }
}


